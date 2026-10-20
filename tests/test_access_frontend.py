import subprocess
from pathlib import Path


def testEngineerScreensAvoidSupervisorRequests():
  root=Path(__file__).resolve().parents[1]
  result=subprocess.run(['node',str(root/'tests/access_frontend_scenario.cjs')],cwd=root,
                        capture_output=True,text=True,encoding='utf-8',timeout=30)
  assert result.returncode==0,result.stdout+result.stderr
