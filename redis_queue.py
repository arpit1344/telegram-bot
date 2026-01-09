import json
import redis

r = redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True
)

def qkey(bot, source):
    return f"queue:{bot}:{source}"

def push(bot, source, message):
    r.rpush(qkey(bot, source), json.dumps(message))

def pop(bot, source):
    data = r.lpop(qkey(bot, source))
    return json.loads(data) if data else None

def size(bot, source):
    return r.llen(qkey(bot, source))

def total_size(bot):
    total = 0
    for key in r.scan_iter(f"queue:{bot}:*"):
        total += r.llen(key)
    return total
