"""Synthetic stand-ins for booru pages: neutral content, but the same shapes the parser must handle."""

MD5 = "abcdef0123456789abcdef0123456789"


def list_page(first_id, count, host="img.example.com", popular=True):
    """List page with id="pNNN" anchors, a decoy "original" tag link, a pager link and repeated view links."""
    ids = [first_id - 3 * i for i in range(count)]
    thumbs = "".join(
        f'<span class="thumb"><a id="p{i}" href="index.php?page=post&amp;s=view&amp;id={i}">'
        f'<img src="https://{host}/thumbnails//ab/cd/thumbnail_{i:032x}.jpg" alt="landscape tree" '
        f'title="landscape tree rating:safe"/></a></span>' for i in ids)
    popular_block = "".join(f'<a href="index.php?page=post&amp;s=view&amp;id={i}">top</a>'
                            for i in ids[:5]) if popular else ""
    sidebar = '<li class="tag-type-copyright"><a href="index.php?page=post&amp;s=list&amp;tags=original">original</a></li>'
    pager = '<a href="index.php?page=post&amp;s=list&amp;tags=landscape&amp;pid=42">2</a>'
    return f"<html><body><ul>{sidebar}</ul><div>{thumbs}</div>{popular_block}<div>{pager}</div></body></html>"


def post_page(style):
    """The lines of a post page that mention image files, in the three layouts seen in the wild."""
    host = "https://img.example.com"
    if style == "gelbooru":      # og:image, decoy 'original' tag link, sample/original links
        return (f'<meta property="og:image" content="{host}//images/ab/cd/{MD5}.webm" />\n'
                '<li><a href="index.php?page=post&amp;s=list&amp;tags=original">original</a></li>\n'
                f'<li><a href="//reverse.example/search.php?url={host}/thumbnails//ab/cd/thumbnail_{MD5}.jpg">Reverse</a></li>\n'
                f'<li><a href="javascript:;" onclick="$(\'#image\').attr(\'src\',\'{host}/images/ab/cd/{MD5}.webm\');">Fit</a></li>\n'
                f'<li><a href="{host}/images/ab/cd/{MD5}.webm" target="_blank">Original image</a></li>\n'), f"{MD5}.webm"
    if style == "hypnohub":      # cache-buster, sample image, wrapper link
        return (f'<meta property="og:image" content="{host}//images/ab/cd/{MD5}.gif?282186" />\n'
                f'<img src="{host}//samples/ab/cd/sample_{MD5}.jpg?282186" id="image" />\n'
                f'<a href="{host}//images/ab/cd/{MD5}.gif?282186">Original image</a>\n'
                f'<li><a href="http://reverse.example/search.php?url={host}/thumbnails//ab/cd/thumbnail_{MD5}.jpg">Reverse</a></li>\n'
                f'<li><a href="http://upscale.example/Home/fromlink?denoise=1&scale=2&url={host}//images/ab/cd/{MD5}.gif">Upscale</a></li>\n'), f"{MD5}.gif"
    return (f'<img alt="landscape tree" src="https://realbooru.example//images/ab/cd/{MD5}.jpeg" id="image"/>\n'
            f'<a href="https://realbooru.example//images/ab/cd/{MD5}.jpeg">Original</a>\n'), f"{MD5}.jpeg"
