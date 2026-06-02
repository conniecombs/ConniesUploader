import re

def test():
    template = "[center][img]#cover_url#[/img]\n[img]#cover_url#[/img]\n\n#all_images#[/center]"
    images = [("v1", "t1", "d1"), ("v2", "t2", "d2"), ("v3", "t3", "d3")]
    data = {"cover_url": "t1"}

    cover_count = template.count("#cover_url#")
    covers_extracted = []
    if cover_count > 0:
        for img in images[:cover_count]:
            viewer_url = img[0] if len(img) > 0 else ""
            thumb_url = img[1] if len(img) > 1 else viewer_url
            covers_extracted.append(thumb_url)
        remaining_images = images[cover_count:]
    else:
        remaining_images = images

    filtered_images = []
    for img in remaining_images:
        viewer_url = img[0] if len(img) > 0 else ""
        thumb_url = img[1] if len(img) > 1 else viewer_url
        direct_url = img[2] if len(img) > 2 else viewer_url
        filtered_images.append((viewer_url, thumb_url, direct_url))

    print(f"Covers extracted: {covers_extracted}")
    print(f"Filtered images: {filtered_images}")

    # Process all_images
    processed_images = []
    for v_url, t_url, d_url in filtered_images:
        processed_images.append(f"[url={v_url}][img]{t_url}[/img][/url]")
    data["all_images"] = " ".join(processed_images)

    content = template
    # Replace cover_url sequentially
    covers_to_use = covers_extracted.copy()
    def cover_repl(match):
        if covers_to_use:
            return covers_to_use.pop(0)
        return ""
    
    content = re.sub(r"#cover_url#", cover_repl, content)
    
    for k, v in data.items():
        if k == "cover_url": continue
        content = content.replace(f"#{k}#", str(v))

    print("Result:")
    print(content)

test()
