# agentshield_core/app/utils/fast_json.py
import orjson

def dumps(obj, sort_keys=False, default=None):
    """
    Drop-in replacement for json.dumps using orjson (Rust).
    Returns str (decodes bytes from orjson).
    """
    option = 0
    if sort_keys:
        option |= orjson.OPT_SORT_KEYS
    
    # orjson returns bytes, so we decode to str for compatibility with standard json usage
    return orjson.dumps(obj, default=default, option=option).decode('utf-8')

def loads(obj):
    """
    Drop-in replacement for json.loads using orjson (Rust).
    """
    return orjson.loads(obj)
