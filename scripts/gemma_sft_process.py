"""啟動前建立整組 ownership，收束後代後才交還下一個實驗階段。"""
import math
import os
import signal
import subprocess
import time


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


class PosixProcessGroup:
  def __init__(self, command, cwd, environment, log):
    if not hasattr(os, 'waitid') or not hasattr(os, 'WNOWAIT'):
      raise RuntimeError('Owned POSIX groups require waitid/WNOWAIT support')
    self.process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log,
      stderr=subprocess.STDOUT, start_new_session=True)
    self.pid = self.process.pid
    self.stopped = False
    self.returncode = None

  def wait(self, timeout=None):
    deadline = None if timeout is None else time.monotonic() + timeout
    while self.returncode is None:
      # 保留 leader 的 waitable PID，直到整組清理完成，避免 PGID 被重用。
      status = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
      if status is not None:
        self.returncode = status.si_status if status.si_code == os.CLD_EXITED else -status.si_status
      elif deadline is not None and time.monotonic() >= deadline:
        raise subprocess.TimeoutExpired(self.process.args, timeout)
      else:
        time.sleep(0.01)
    return self.returncode

  def hasActiveMembers(self):
    rows = subprocess.check_output(['ps', '-axo', 'pgid=,stat='], text=True, timeout=2).splitlines()
    if not rows:
      raise RuntimeError('Cannot confirm owned group state')
    for row in rows:
      groupId, state = row.split()
      if int(groupId) == self.pid and not state.startswith('Z'):
        return True
    return False

  def stop(self):
    if self.stopped:
      return
    # 父程序已退出時 process group 仍可能存在，不能依 poll() 略過清理。
    try:
      os.killpg(self.pid, signal.SIGKILL)
    except ProcessLookupError:
      pass
    deadline = time.monotonic() + 15
    # orphan zombie 不再執行工作；仍在執行或不可中斷的後代則不能放行下一階段。
    while self.hasActiveMembers():
      if time.monotonic() >= deadline:
        raise TimeoutError('Owned process group still has active processes')
      time.sleep(0.01)
    self.returncode = self.process.wait(timeout=15)
    self.stopped = True

  def close(self):
    self.stop()


class WindowsJobProcess:
  def __init__(self, command, cwd, environment, log):
    import ctypes
    import _winapi
    import msvcrt
    from ctypes import wintypes
    self.ctypes = ctypes
    self.api = _winapi
    self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    self.command = command
    self.returncode = None
    self.job = None
    self.handle = None
    class BasicLimits(ctypes.Structure):
      _fields_ = [('processTime', ctypes.c_longlong), ('jobTime', ctypes.c_longlong),
        ('flags', wintypes.DWORD), ('minimumWorkingSet', ctypes.c_size_t),
        ('maximumWorkingSet', ctypes.c_size_t), ('activeProcessLimit', wintypes.DWORD),
        ('affinity', ctypes.c_size_t), ('priorityClass', wintypes.DWORD),
        ('schedulingClass', wintypes.DWORD)]
    class ExtendedLimits(ctypes.Structure):
      _fields_ = [('basic', BasicLimits), ('ioCounters', ctypes.c_ulonglong * 6),
        ('processMemoryLimit', ctypes.c_size_t), ('jobMemoryLimit', ctypes.c_size_t),
        ('peakProcessMemoryUsed', ctypes.c_size_t), ('peakJobMemoryUsed', ctypes.c_size_t)]
    class Accounting(ctypes.Structure):
      _fields_ = [('times', ctypes.c_longlong * 4), ('pageFaults', wintypes.DWORD),
        ('totalProcesses', wintypes.DWORD), ('activeProcesses', wintypes.DWORD),
        ('terminatedProcesses', wintypes.DWORD)]
    self.accountingType = Accounting
    signatures = {
      'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
      'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
      'QueryInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
      'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
      'TerminateJobObject': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
      'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
      'TerminateProcess': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
      'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
      'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, resultType) in signatures.items():
      function = getattr(self.kernel, name)
      function.argtypes = arguments
      function.restype = resultType
    threadHandle = None
    inherited = []
    assigned = False
    try:
      self.job = self.kernel.CreateJobObjectW(None, None)
      self.check(self.job)
      limits = ExtendedLimits()
      limits.basic.flags = 0x2000
      self.check(self.kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
      current = _winapi.GetCurrentProcess()
      with open(os.devnull, 'rb') as nullInput:
        for descriptor in [nullInput.fileno(), log.fileno()]:
          inherited.append(_winapi.DuplicateHandle(current, msvcrt.get_osfhandle(descriptor), current, 0, True, 2))
      startup = subprocess.STARTUPINFO()
      startup.dwFlags = subprocess.STARTF_USESTDHANDLES
      startup.hStdInput, startup.hStdOutput = inherited
      startup.hStdError = startup.hStdOutput
      startup.lpAttributeList = {'handle_list': inherited}
      # 暫停建立後先加入禁止 breakaway 的 job，任何使用者程式碼都不能搶先產生後代。
      self.handle, threadHandle, self.pid, _ = _winapi.CreateProcess(None,
        subprocess.list2cmdline(command), None, None, True, 0x4 | 0x08000000,
        environment, str(cwd), startup)
      self.check(self.kernel.AssignProcessToJobObject(self.job, self.handle))
      assigned = True
      if self.kernel.ResumeThread(threadHandle) == 0xffffffff:
        raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
      try:
        if self.handle and not assigned:
          terminateOwnedHandle(self.kernel, self.handle, lambda: ctypes.WinError(ctypes.get_last_error()))
      finally:
        self.close()
      raise
    finally:
      for handle in [threadHandle, *inherited]:
        if handle:
          _winapi.CloseHandle(handle)

  def check(self, result):
    if not result:
      raise self.ctypes.WinError(self.ctypes.get_last_error())

  def wait(self, timeout=None):
    if self.returncode is not None:
      return self.returncode
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
      remaining = 0.05 if deadline is None else min(0.05, max(0, deadline - time.monotonic()))
      status = self.api.WaitForSingleObject(self.handle, math.ceil(remaining * 1000))
      if status == 0:
        break
      if status != 258:
        raise OSError(f'Unexpected process wait status: {status}')
      if deadline is not None and time.monotonic() >= deadline:
        raise subprocess.TimeoutExpired(self.command, timeout)
    self.returncode = self.api.GetExitCodeProcess(self.handle)
    return self.returncode

  def activeCount(self):
    accounting = self.accountingType()
    self.check(self.kernel.QueryInformationJobObject(self.job, 1,
      self.ctypes.byref(accounting), self.ctypes.sizeof(accounting), None))
    return accounting.activeProcesses

  def stop(self):
    if not self.job:
      return
    self.check(self.kernel.TerminateJobObject(self.job, 1))
    deadline = time.monotonic() + 15
    while self.activeCount():
      if time.monotonic() >= deadline:
        raise TimeoutError('Owned job still has active processes')
      time.sleep(0.01)
    if self.handle:
      self.wait(timeout=15)

  def close(self):
    try:
      self.stop()
    finally:
      # job handle 不繼承給 child；關閉最後 handle 也是 supervisor 退出時的保險。
      for attribute in ['job', 'handle']:
        handle = getattr(self, attribute)
        if handle:
          self.kernel.CloseHandle(handle)
          setattr(self, attribute, None)


def startOwnedProcess(command, cwd, environment, log):
  processType = WindowsJobProcess if os.name == 'nt' else PosixProcessGroup
  return processType(command, cwd, environment, log)
