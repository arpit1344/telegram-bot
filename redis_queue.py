import json
import redis

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def qkey(bot, source):
    return f"queue:{bot}:{source}"

def push(bot, source, msg):
    r.rpush(qkey(bot, source), json.dumps(msg))

def pop(bot, source):
    data = r.lpop(qkey(bot, source))
    return json.loads(data) if data else None

def size(bot, source):
    return r.llen(qkey(bot, source))

def total(bot):
    total_count = 0
    for k in r.scan_iter(f"queue:{bot}:*"):
        total_count += r.llen(k)
    return total_count
