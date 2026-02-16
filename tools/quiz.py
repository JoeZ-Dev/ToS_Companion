import re
import urllib.request
from html import unescape


def decode_secret_message(url: str) -> None:
    html = urllib.request.urlopen(url).read().decode("utf-8", "replace")

    # Grab table rows, then cells (th/td). Unescape HTML entities.
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        cells = [unescape(re.sub(r"<.*?>", "", c)).strip()
                 for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)]
        if cells:
            rows.append(cells)

    # Find the header row and determine column indices
    header_i = next(i for i, r in enumerate(rows)
                    if any("x-coordinate" in c.lower() for c in r) and any("y-coordinate" in c.lower() for c in r))
    header = [c.lower() for c in rows[header_i]]
    xi = next(i for i, c in enumerate(header) if "x-coordinate" in c)
    yi = next(i for i, c in enumerate(header) if "y-coordinate" in c)
    ci = next(i for i, c in enumerate(header) if "character" in c)

    # Parse points and bounds
    pts, max_x, max_y = {}, 0, 0
    for r in rows[header_i + 1:]:
        if len(r) <= max(xi, yi, ci):
            continue
        try:
            x, y = int(r[xi]), int(r[yi])
        except ValueError:
            continue
        ch = r[ci] or " "
        pts[(x, y)] = ch
        max_x, max_y = max(max_x, x), max(max_y, y)

    # Build + print (0,0 is bottom-left => print y from max_y down to 0)
    for y in range(max_y, -1, -1):
        print("".join(pts.get((x, y), " ") for x in range(max_x + 1)))


def main():
    default = "https://docs.google.com/document/d/e/2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub"
    url = input(f"Enter published Google Doc URL (Enter = default):\n{default}\n> ").strip() or default
    decode_secret_message(url)


if __name__ == "__main__":
    main()
