"""Fail CI if pytest didn't execute tests or silently skipped part of the suite."""
import sys
from xml.etree import ElementTree

root=ElementTree.parse(sys.argv[1]).getroot()
suites=[root] if root.tag=='testsuite' else root.findall('testsuite')
counts={key:sum(int(s.get(key,0)) for s in suites) for key in ['tests','failures','errors','skipped']}
print(counts)
if counts['tests']<=0 or any(counts[k] for k in ['failures','errors','skipped']):
    raise SystemExit('Tests must execute with zero failures, errors and skips.')
