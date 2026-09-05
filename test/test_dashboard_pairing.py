from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from nekosuneai.dashboard_runtime_fix_patch import DASHBOARD_RUNTIME_UI


class Scripts(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.scripts = []
        self.active = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.active = tag == "script" and "src" not in dict(attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.scripts.append(data)


def run_node(program, source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for dashboard JavaScript checks")
    result = subprocess.run([node, "-e", program], input=json.dumps(source), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_pairing_scripts_parse():
    scripts = Scripts(Path("nekosuneai/static/automations.html").read_text("utf-8")).scripts
    scripts += Scripts(DASHBOARD_RUNTIME_UI).scripts
    run_node("const vm=require('node:vm');for(const s of JSON.parse(require('node:fs').readFileSync(0,'utf8')))new vm.Script(s);", scripts)


def test_dashboard_approval_code_and_error_controls():
    scripts = Scripts(Path("nekosuneai/static/automations.html").read_text("utf-8")).scripts
    run_node(r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
  constructor(){this.children=[];this.classList={add(){},remove(){},toggle(){}};this.value='Gaming PC';this.textContent='';}
  appendChild(child){this.children.push(child)}
  replaceChildren(){this.children=[]}
}
const elements=new Map(),calls=[];
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
let pending=[{request_id:'request-1',name:'Gaming PC',device_type:'windows-gaming',remote_ip:'192.168.1.10'}],fail=false;
const context=vm.createContext({URLSearchParams,location:{search:''},document:{getElementById:get,createElement:()=>new Element()},setInterval(){},setTimeout(){},confirm:()=>true,
  fetch:async(path,options)=>{
    calls.push({path,options});
    if(path==='/api/pairing/approve'||path==='/api/pairing/reject')pending=[];
    const body=path==='/api/pairing/pending'?{pending}:path==='/api/nodes/pairing'?{pairing_id:'id-1',pairing_code:'ABC123'}:{nodes:[],routines:[],conflicts:[],result:{devices:[],status:{}}};
    return {ok:!fail,json:async()=>fail?{error:'session expired'}:body};
  }
});
(async()=>{
  for(const script of JSON.parse(require('node:fs').readFileSync(0,'utf8')))vm.runInContext(script,context);
  await new Promise(resolve=>setImmediate(resolve));
  const row=get('pairing-requests').children[0];
  assert.match(row.children[0].textContent,/Gaming PC \(windows-gaming\)/);
  assert.equal(row.children[1].textContent,'Approve');
  await row.children[1].onclick();
  const approval=calls.find(x=>x.path==='/api/pairing/approve');
  assert.equal(JSON.parse(approval.options.body).request_id,'request-1');
  assert.equal(approval.options.credentials,'same-origin');
  assert.equal(get('pairing-requests').textContent,'No pending pairing requests.');
  await vm.runInContext('createPairing()',context);
  assert.match(get('pair-result').innerHTML,/id-1/);
  assert.match(get('pair-result').innerHTML,/ABC123/);
  fail=true;
  await vm.runInContext('loadPairingRequests()',context);
  assert.match(get('pairing-requests').textContent,/session expired/);
  assert.equal(calls.find(x=>x.path==='/api/pairing/pending').options.cache,'no-store');
})().catch(error=>{console.error(error);process.exitCode=1});
''', scripts)
