from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .database import get_state, set_state

STATE_KEY = "assistant_reminders_v1"

@dataclass
class Reminder:
    id: str
    message: str
    due_epoch: float
    created_epoch: float
    repeat_seconds: int = 0
    active: bool = True
    kind: str = "reminder"

def _load() -> list[Reminder]:
    try:
        rows = json.loads(get_state(STATE_KEY, "[]")); return [Reminder(**row) for row in rows if isinstance(row, dict)]
    except (TypeError, ValueError): return []

def _save(rows: list[Reminder]) -> None: set_state(STATE_KEY, json.dumps([asdict(x) for x in rows], ensure_ascii=False))

def _parse_duration(lower: str) -> tuple[int, str] | None:
    m = re.search(r"\b(?:for|in)\s+(\d+)\s*(seconds?|minutes?|hours?|days?)\b", lower)
    if not m: return None
    n=max(1,int(m.group(1))); unit=m.group(2); sec=n*(86400 if unit.startswith('day') else 3600 if unit.startswith('hour') else 60 if unit.startswith('minute') else 1)
    return sec,m.group(0)

def _parse_due(text: str, tz: ZoneInfo) -> tuple[float, str] | None:
    lower=text.lower().strip(); now=datetime.now(tz)
    dur=_parse_duration(lower)
    if dur: return now.timestamp()+dur[0],dur[1]
    tm=re.search(r"\b(?:at|for)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",lower)
    if tm:
        hour=int(tm.group(1))%12
        if tm.group(3)=='pm': hour+=12
        minute=int(tm.group(2) or 0); due=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
        if 'tomorrow' in lower: due+=timedelta(days=1)
        elif due<=now: due+=timedelta(days=1)
        return due.timestamp(),tm.group(0)
    return None

def parse_reminder_request(text: str, tz: ZoneInfo) -> tuple[str, object] | None:
    lower=text.lower().strip()
    if re.search(r"\b(?:list|show)\b.*\b(?:reminders|timers|alarms)\b",lower): return 'list',None
    if re.search(r"\b(?:clear|delete|remove|cancel)\s+all\s+(?:reminders|timers|alarms)\b",lower): return 'clear',None
    m=re.search(r"\b(?:cancel|delete|remove)\s+(?:reminder|timer|alarm)\s+([a-f0-9]{8})\b",lower)
    if m: return 'remove',m.group(1)

    kind='reminder'
    if 'timer' in lower: kind='timer'
    elif 'alarm' in lower or 'wake me' in lower: kind='alarm'
    is_request=('remind me' in lower or re.search(r"\bset (?:a )?(?:reminder|timer|alarm)\b",lower) or 'wake me' in lower)
    if not is_request: return None
    parsed=_parse_due(text,tz)
    if not parsed: return 'error','I need a time, for example: set a 20 minute timer, wake me at 7 AM, or remind me in 2 hours to check the oven.'
    due,matched=parsed

    if kind=='timer':
        message='your timer is finished'
        label=re.search(r"\b(?:called|named)\s+(.+)$",text,re.I)
        if label: message=f"{label.group(1).strip()} timer is finished"
    elif kind=='alarm':
        message='your alarm is going off'
    else:
        message=re.sub(r"^.*?\bremind me\b",'',text,flags=re.I).strip(' ,.-')
        message=re.sub(r"^.*?\bset (?:a )?reminder\b",'',message,flags=re.I).strip(' ,.-')
        message=re.sub(re.escape(matched),'',message,count=1,flags=re.I).strip(' ,.-')
        message=re.sub(r"\b(?:today|tomorrow)\b",'',message,flags=re.I).strip(' ,.-')
        message=re.sub(r"^to\s+",'',message,flags=re.I).strip() or 'your reminder'
    return 'create',Reminder(uuid.uuid4().hex[:8],message,due,time.time(),0,True,kind)

class ReminderManager:
    def __init__(self, notify: Callable[[str,str],None], timezone: str='Europe/London') -> None:
        self.notify=notify; self.tz=ZoneInfo(timezone); self._stop=threading.Event(); self._thread: threading.Thread|None=None; self._lock=threading.RLock()
    def start(self)->None:
        if self._thread and self._thread.is_alive(): return
        self._thread=threading.Thread(target=self._loop,daemon=True,name='assistant-reminders'); self._thread.start()
    def handle(self,text:str)->str|None:
        parsed=parse_reminder_request(text,self.tz)
        if not parsed:return None
        action,value=parsed
        with self._lock:
            rows=_load()
            if action=='error':return str(value)
            if action=='clear':
                count=sum(1 for x in rows if x.active)
                for x in rows:x.active=False
                _save(rows);return f'Cancelled {count} reminder/timer/alarm item(s).'
            if action=='remove':
                found=False
                for x in rows:
                    if x.id==value and x.active:x.active=False;found=True
                _save(rows);return f'Cancelled {value}.' if found else f"I couldn't find {value}."
            if action=='list':
                active=sorted((x for x in rows if x.active),key=lambda x:x.due_epoch)
                if not active:return "You don't have any active reminders, timers, or alarms."
                return 'Active reminders, timers and alarms:\n'+'\n'.join(f"- {x.id}: {x.kind}, {x.message}, {datetime.fromtimestamp(x.due_epoch,self.tz).strftime('%A %H:%M')}" for x in active[:20])
            item=value; assert isinstance(item,Reminder); rows.append(item); _save(rows)
            shown=datetime.fromtimestamp(item.due_epoch,self.tz).strftime('%A at %I:%M %p').replace(' 0',' ')
            if item.kind=='timer': return f"Timer set for {shown}."
            if item.kind=='alarm': return f"Alarm set for {shown}."
            return f"Okay. I'll remind you to {item.message} on {shown}."
    def _loop(self)->None:
        while not self._stop.wait(1):
            now=time.time();fired=[]
            with self._lock:
                rows=_load()
                for item in rows:
                    if item.active and item.due_epoch<=now:item.active=False;fired.append(item)
                if fired:_save(rows)
            for item in fired:
                prefix='Alarm' if item.kind=='alarm' else 'Timer' if item.kind=='timer' else 'Reminder'
                self.notify(f'{prefix}: {item.message}','warning')
