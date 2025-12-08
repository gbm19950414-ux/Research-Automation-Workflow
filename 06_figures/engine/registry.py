# registry module placeholder
# engine/registry.py
PLOTTERS = {}

def register(name):
    """装饰器，用于注册绘图函数"""
    def decorator(func):
        PLOTTERS[name] = func
        return func
    return decorator