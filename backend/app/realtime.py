import asyncio
from collections import defaultdict

class EventBroker:
    def __init__(self):self.queues=defaultdict(list)
    async def publish(self,topic:str,event:dict):
        for q in list(self.queues[topic]):
            try:q.put_nowait(event)
            except Exception:
                if q in self.queues[topic]:self.queues[topic].remove(q)
    async def subscribe(self,topic:str):
        q=asyncio.Queue(maxsize=100);self.queues[topic].append(q)
        try:
            while True:yield await q.get()
        finally:
            if q in self.queues[topic]:self.queues[topic].remove(q)

broker=EventBroker()
