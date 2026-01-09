import json, redis

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def key(bot, src):
    return f"queue:{bot}:{src}"

def push(bot, src, msg):
    r.rpush(key(bot, src), json.dumps(msg))

def pop(bot, src):
    d = r.lpop(key(bot, src))
    return json.loads(d) if d else None

def size(bot, src):
    return r.llen(key(bot, src))

def total(bot):
    t = 0
    for k in r.scan_iter(f"queue:{bot}:*"):
        t += r.llen(k)
    return t
