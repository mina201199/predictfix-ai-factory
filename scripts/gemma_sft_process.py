"""Windows 子程序清理：僅處理持有根 handle 的已知後代，不依賴 WMI 或額外套件。"""


def isOwnedEdge(parentPid, childPid, parents, created):
  return parents.get(childPid) == parentPid and created[childPid] >= created[parentPid]


def terminateOwnedHandle(kernel, handle, errorFactory):
  if kernel.WaitForSingleObject(handle, 0) == 0:
    return
  if not kernel.TerminateProcess(handle, 1):
    error = errorFactory()
    # venv 啟動器會隨子程序自行退出；已退出的 handle 也可能回報 Access denied。
    if kernel.WaitForSingleObject(handle, 5000) == 0:
      return
    raise error
  if kernel.WaitForSingleObject(handle, 5000) != 0:
    raise TimeoutError('Owned process did not stop')


def stopWindowsTree(rootPid, rootHandle):
  import ctypes
  from ctypes import wintypes
  kernel = ctypes.WinDLL('kernel32', use_last_error=True)
  class ProcessEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
      ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
      ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
      ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
      ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
  signatures = {
    'CreateToolhelp32Snapshot': ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
    'Process32FirstW': ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
    'Process32NextW': ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
    'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
    'GetProcessId': ([wintypes.HANDLE], wintypes.DWORD),
    'GetProcessTimes': ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
    'TerminateProcess': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
    'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
    'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
  }
  for name, (arguments, resultType) in signatures.items():
    function = getattr(kernel, name)
    function.argtypes = arguments
    function.restype = resultType
  if kernel.GetProcessId(rootHandle) != rootPid:
    raise ValueError('Root handle does not match owned process')
  def creationTime(handle):
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
      raise ctypes.WinError(ctypes.get_last_error())
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
  def parentSnapshot():
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
      raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
      entry = ProcessEntry()
      entry.dwSize = ctypes.sizeof(entry)
      valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
      while valid:
        parents[entry.th32ProcessID] = entry.th32ParentProcessID
        valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
      if ctypes.get_last_error() not in (0, 18):
        raise ctypes.WinError(ctypes.get_last_error())
      return parents
    finally:
      kernel.CloseHandle(snapshot)
  parents = parentSnapshot()
  order = [rootPid]
  handles = {rootPid: rootHandle}
  created = {rootPid: creationTime(rootHandle)}
  try:
    for ancestor in order:
      for pid, parent in parents.items():
        if parent == ancestor and pid not in handles:
          handle = kernel.OpenProcess(0x00101001, False, pid)
          if not handle:
            error = ctypes.get_last_error()
            if error == 87:
              continue
            raise ctypes.WinError(error)
          handles[pid] = handle
          created[pid] = creationTime(handle)
          # 舊父退出後 PID 可能重用；較早出生的程序不能算新父的後代。
          if not isOwnedEdge(ancestor, pid, parents, created):
            kernel.CloseHandle(handles.pop(pid))
            created.pop(pid)
            continue
          order.append(pid)
    # handle 持續保留到清理完成，並再次核對 ancestry，避免 PID 重用誤傷無關程序。
    currentParents = parentSnapshot()
    owned = {rootPid}
    for pid in order[1:]:
      if parents[pid] in owned and isOwnedEdge(parents[pid], pid, currentParents, created):
        owned.add(pid)
    for pid in reversed(order):
      if pid not in owned:
        continue
      handle = handles[pid]
      terminateOwnedHandle(kernel, handle, lambda: ctypes.WinError(ctypes.get_last_error()))
  finally:
    for pid, handle in handles.items():
      if pid != rootPid:
        kernel.CloseHandle(handle)
