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
    paused_remaining_seconds: float = 0.0
    repeat_pattern: str = ""
    last_fired_epoch: float = 0.0

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

def _repeat_pattern(lower: str) -> str:
    if re.search(r"\bevery\s+(?:weekdays?|working day)\b",lower):return 'weekdays'
    if re.search(r"\bevery\s+day\b|\bdaily\b",lower):return 'daily'
    return ''

def parse_reminder_request(text: str, tz: ZoneInfo) -> tuple[str, object] | None:
    lower=text.lower().strip()
    m=re.search(r"\bsnooze(?:\s+(?:(?:the|my)\s+)?(.+?)\s+alarm)?\s+(?:for\s+)?(\d+)\s*(seconds?|minutes?|hours?)\b",lower)
    if m:
        amount=max(1,int(m.group(2)));unit=m.group(3)
        seconds=amount*(3600 if unit.startswith('hour') else 60 if unit.startswith('minute') else 1)
        return 'snooze',{'selector':(m.group(1) or '').strip(),'seconds':seconds}
    m=re.search(r"\b(?:dismiss|stop)\s+(?:(?:the|my)\s+)?(?:(.+?)\s+)?alarm\b",lower)
    if m:return 'dismiss',{'kind':'alarm','selector':(m.group(1) or '').strip()}
    if re.search(r"\b(?:list|show)\b.*\b(?:reminders|timers|alarms)\b",lower): return 'list',None
    if re.search(r"\b(?:clear|delete|remove|cancel)\s+all\s+(?:reminders|timers|alarms)\b",lower): return 'clear',None
    m=re.search(r"\b(cancel|delete|remove|pause|resume|continue)\s+(?:(?:the|my)\s+)?(.+?)\s+(reminder|timer|alarm)\b",lower)
    if m:
        action={'cancel':'remove','delete':'remove','remove':'remove','pause':'pause','resume':'resume','continue':'resume'}[m.group(1)]
        return action, {'kind':m.group(3),'selector':m.group(2).strip()}
    m=re.search(r"\b(cancel|delete|remove|pause|resume|continue)\s+(?:reminder|timer|alarm)\s+([a-f0-9]{8})\b",lower)
    if m:
        action={'cancel':'remove','delete':'remove','remove':'remove','pause':'pause','resume':'resume','continue':'resume'}[m.group(1)]
        return action, {'kind':None,'selector':m.group(2)}

    kind='reminder'
    if 'timer' in lower: kind='timer'
    elif 'alarm' in lower or 'wake me' in lower: kind='alarm'
    is_request=('remind me' in lower or re.search(r"\bset (?:(?:a|an) )?(?:reminder|timer|alarm)\b",lower) or 'wake me' in lower)
    if not is_request: return None
    parsed=_parse_due(text,tz)
    if not parsed: return 'error','I need a time, for example: set a 20 minute timer, wake me at 7 AM, or remind me in 2 hours to check the oven.'
    due,matched=parsed

    if kind=='timer':
        message='your timer is finished'
        label=re.search(r"\b(?:called|named)\s+(.+)$",text,re.I)
        if label: message=f"{label.group(1).strip()} timer is finished"
    elif kind=='alarm':
        label=re.search(r"\b(?:called|named)\s+(.+?)(?:\s+every\s+(?:day|weekday|weekdays))?$",text,re.I)
        message=f"{label.group(1).strip()} alarm is going off" if label else 'your alarm is going off'
    else:
        message=re.sub(r"^.*?\bremind me\b",'',text,flags=re.I).strip(' ,.-')
        message=re.sub(r"^.*?\bset (?:a )?reminder\b",'',message,flags=re.I).strip(' ,.-')
        message=re.sub(re.escape(matched),'',message,count=1,flags=re.I).strip(' ,.-')
        message=re.sub(r"\b(?:today|tomorrow)\b",'',message,flags=re.I).strip(' ,.-')
        message=re.sub(r"^to\s+",'',message,flags=re.I).strip() or 'your reminder'
    repeat=_repeat_pattern(lower) if kind in {'alarm','reminder'} else ''
    return 'create',Reminder(uuid.uuid4().hex[:8],message,due,time.time(),0,True,kind,0.0,repeat)

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
                count=sum(1 for x in rows if x.active or x.paused_remaining_seconds>0)
                for x in rows:x.active=False;x.paused_remaining_seconds=0.0
                _save(rows);return f'Cancelled {count} reminder/timer/alarm item(s).'
            if action in {'remove','pause','resume'}:
                target,error=self._find_target(rows,value,action)
                if error:return error
                assert target is not None
                if action=='remove':
                    target.active=False;target.paused_remaining_seconds=0.0
                    reply=f'Cancelled {target.id} ({self._label(target)}).'
                elif action=='pause':
                    target.paused_remaining_seconds=max(1.0,target.due_epoch-time.time());target.active=False
                    reply=f'Paused {self._label(target)}.'
                else:
                    target.due_epoch=time.time()+target.paused_remaining_seconds;target.paused_remaining_seconds=0.0;target.active=True
                    reply=f'Resumed {self._label(target)}.'
                _save(rows);return reply
            if action in {'snooze','dismiss'}:
                target,error=self._find_recent_alarm(rows,value)
                if error:return error
                assert target is not None
                if action=='snooze':
                    seconds=int(value['seconds']);target.due_epoch=time.time()+seconds;target.active=True
                    reply=f'Snoozed {self._label(target)} for {self._duration_text(seconds)}.'
                else:
                    target.active=False;target.repeat_pattern='';target.paused_remaining_seconds=0.0
                    reply=f'Dismissed {self._label(target)}.'
                _save(rows);return reply
            if action=='list':
                active=sorted((x for x in rows if x.active),key=lambda x:x.due_epoch)
                paused=sorted((x for x in rows if x.paused_remaining_seconds>0),key=lambda x:x.created_epoch)
                if not active and not paused:return "You don't have any active reminders, timers, or alarms."
                lines=[f"- {x.id}: {x.kind}, {x.message}, {datetime.fromtimestamp(x.due_epoch,self.tz).strftime('%A %H:%M')}{' ('+x.repeat_pattern+')' if x.repeat_pattern else ''}" for x in active[:20]]
                lines.extend(f"- {x.id}: {x.kind}, {x.message}, paused" for x in paused[:max(0,20-len(lines))])
                return 'Active reminders, timers and alarms:\n'+'\n'.join(lines)
            item=value; assert isinstance(item,Reminder); rows.append(item); _save(rows)
            shown=datetime.fromtimestamp(item.due_epoch,self.tz).strftime('%A at %I:%M %p').replace(' 0',' ')
            if item.kind=='timer': return f"Timer set for {shown}."
            if item.kind=='alarm': return f"Alarm set for {shown}{' and repeating '+item.repeat_pattern if item.repeat_pattern else ''}."
            return f"Okay. I'll remind you to {item.message} on {shown}."

    @staticmethod
    def _label(item: Reminder) -> str:
        label=item.message.lower()
        suffix=f" {item.kind} is finished" if item.kind=='timer' else f" {item.kind} is going off"
        if label.endswith(suffix): label=label[:-len(suffix)]
        if item.kind=='timer' and label=='your': label='unnamed'
        return f"{label} {item.kind}".strip()

    @staticmethod
    def _duration_text(seconds:int)->str:
        if seconds%3600==0:return f'{seconds//3600} hour(s)'
        if seconds%60==0:return f'{seconds//60} minute(s)'
        return f'{seconds} second(s)'

    def _find_recent_alarm(self,rows:list[Reminder],value:object)->tuple[Reminder|None,str|None]:
        request=value if isinstance(value,dict) else {}
        selector=str(request.get('selector','')).strip().lower()
        candidates=[x for x in rows if x.kind=='alarm' and (x.active or x.last_fired_epoch>0)]
        if selector:candidates=[x for x in candidates if selector in {x.id,self._label(x).lower().removesuffix(' alarm')}]
        if not candidates:return None,"I couldn't find an alarm to control."
        candidates.sort(key=lambda x:max(x.last_fired_epoch,x.created_epoch),reverse=True)
        if selector and len(candidates)>1:return None,f"I found more than one {selector} alarm. Please use its 8-character ID."
        return candidates[0],None

    def _next_repeat_due(self,item:Reminder,after:float)->float:
        candidate=datetime.fromtimestamp(item.due_epoch,self.tz)+timedelta(days=1)
        if item.repeat_pattern=='weekdays':
            while candidate.weekday()>=5:candidate+=timedelta(days=1)
        while candidate.timestamp()<=after:
            candidate+=timedelta(days=1)
            if item.repeat_pattern=='weekdays':
                while candidate.weekday()>=5:candidate+=timedelta(days=1)
        return candidate.timestamp()

    def _find_target(self, rows: list[Reminder], value: object, action: str) -> tuple[Reminder|None,str|None]:
        request=value if isinstance(value,dict) else {'selector':str(value),'kind':None}
        selector=str(request.get('selector','')).strip().lower()
        kind=request.get('kind')
        candidates=[]
        for item in rows:
            available=item.paused_remaining_seconds>0 if action=='resume' else item.active
            if not available or (kind and item.kind!=kind):continue
            label=self._label(item).lower()
            if item.id==selector or selector in {label,label.removesuffix(f' {item.kind}')}:
                candidates.append(item)
        if not candidates:return None,f"I couldn't find an active {kind or 'reminder, timer, or alarm'} named {selector}."
        if len(candidates)>1:return None,f"I found more than one {selector} {kind or 'item'}. Please use the 8-character ID from the list."
        return candidates[0],None
    def _loop(self)->None:
        while not self._stop.wait(1):
            self._fire_due_once()

    def _fire_due_once(self, now: float|None=None)->int:
        fired=[];current=time.time() if now is None else now
        with self._lock:
            rows=_load()
            for item in rows:
                if item.active and item.due_epoch<=current:
                    item.last_fired_epoch=current;fired.append(item)
                    if item.repeat_pattern:item.due_epoch=self._next_repeat_due(item,current)
                    else:item.active=False
            if fired:_save(rows)
        for item in fired:
            prefix='Alarm' if item.kind=='alarm' else 'Timer' if item.kind=='timer' else 'Reminder'
            self.notify(f'{prefix}: {item.message}','warning')
        return len(fired)
