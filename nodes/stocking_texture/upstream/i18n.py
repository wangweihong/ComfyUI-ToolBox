from ..core.i18n import tr

_EN = {'丝袜引导': 'Stocking guides', '走向': 'Direction', '亮点': 'Sparkles', '隔开': 'Divider',
       '丝袜纹理': 'stocking texture', '原图': 'Original'}


def both(text):
    return (text, _EN.get(text, text))
