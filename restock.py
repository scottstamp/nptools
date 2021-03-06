# Here it is. The holy grail of Neopets automation -- restocking.
import bisect
import datetime
import io
import os
import re
import random

from PIL import Image, ImageDraw, ImageFilter

import lib
import item_db
import inventory
import neotime

re_shop_item = re.compile(r'''<A href=".*?obj_info_id=(\d+)&stock_id=(\d+)&g=(\d+)" onClick=".*?brr=(\d+)';.*?"><IMG src="http://images.neopets.com/items/(.*?)" .*? title="(.*?)" border="1"><BR></A><B>(.*?)</B><BR>(\d+) in stock<BR>Cost: (.*?) NP''')
re_header = re.compile(r'''<td class="contentModuleHeader">(.*?)</td>''')
re_captcha = re.compile(r'''<input type="image" src="/captcha_show\.phtml\?_x_pwned=(.*?)".*>''')

MIN_PROFIT = 1500
MIN_PROFIT_MARGIN = 0.4

always_buy = {
    # 14. Chocolate Factory
    #'Reject Gold Mote Lolly': 700,

    # 68. Coin shop
    'Large Black Collectable Scarab': 40000000,
    'Smiling Space Faerie Coin': 33500000,
    'Scowling Sloth Coin': 30000000,
    'Neopian Times Coin': 12700000,
    'Money Tree Coin': 3000000,
    'Spotted Blue Collectable Scarab': 2500000,
    'Dr Sloth Coin': 2500000,
    #'Polkadot Collectable Scarab': 2777,
}

def find_neopet(img_data, img_name):
    img = Image.open(io.BytesIO(img_data))
    os.makedirs('shop_captchas', exist_ok=True)
    img.save(f'shop_captchas/{img_name}.png')
    filtered = img.filter(ImageFilter.FIND_EDGES)
    filtered.save(f'shop_captchas/{img_name}-filtered.png')
    width, height = img.size
    # Take median x and median y coordinate of N darkest pixels.
    # Impl is a bit slow, but at least conceptually clear
    N = 21
    best_score = -100000
    xys = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            r, g, b = img.getpixel((x, y))
            fr, fg, fb = filtered.getpixel((x, y))
            score = (fr + fg + fb) - (r + g + b)
            xys.append((score, (x, y)))
    xys.sort()
    xys = xys[-N:]
    best_x = sorted(x for _, (x, y) in xys)[N//2]
    best_y = sorted(y for _, (x, y) in xys)[N//2]
    draw = ImageDraw.Draw(img)
    draw.ellipse((best_x - 5, best_y - 5, best_x + 5, best_y + 5), fill=(255, 0, 0))
    for _, (x, y) in xys:
        draw.point((x, y), fill=(255, 255, 0))
    img.save(f'shop_captchas/{img_name}-solved.png')

    # introduce a bit of noise
    best_x += random.randint(-2, 2)
    best_y += random.randint(-2, 2)
    return best_x, best_y

def haggle_price(price):
    #price = int(price * 0.98)
    if price < 100:
        return price
    base = price
    while base >= 100: base //= 10
    base -= 1
    if base < 10: base = 98
    result = base
    while result < price:
        result = result * 10 + (result % 100 // 10)
    result //= 10
    return result

def restock(shop_id):
    inventory.ensure_np(99999)
    np = lib.NeoPage()
    np.get('/objects.phtml', f'obj_type={shop_id}', 'type=shop')
    items = re_shop_item.findall(np.content)
    shop_name = re_header.search(np.content)[1].strip()
    print(f'{len(items)} items found at {shop_name}.')

    # Look for profitable items
    best_score = ()
    best = None
    for obj_info_id, stock_id, g, brr, image, desc, name, stock, price in items:
        price = lib.amt(price)
        # TODO: Here we assume that items with the same name but drastically
        # different value won't restock in shops. For a more fine-grained
        # search, should search using image as well.
        true_price = item_db.get_price(name, update=False) or always_buy.get(name)
        if not true_price:
            continue
        print(f'Item: {stock} x {name} for {price} NP. (True price {true_price} NP)')

        profit = true_price - price
        score = (name in always_buy, profit, profit / price)
        if score > best_score:
            best_score = score
            best = (name, price, obj_info_id, stock_id, brr)

    if not best:
        return

    if best_score and (best_score[0] or best_score[1] >= MIN_PROFIT and best_score[2] >= MIN_PROFIT_MARGIN):
        name, price, obj_info_id, stock_id, brr = best
        np.get('/haggle.phtml', f'obj_info_id={obj_info_id}', f'stock_id={stock_id}', f'brr={brr}')
        referer = np.referer
        _x_pwned = re_captcha.search(np.content)[1]
        np.get('/captcha_show.phtml', f'_x_pwned={_x_pwned}')

        offer = haggle_price(price)
        print(f'Trying to buy {name} for {offer} !!')
        best_x, best_y = find_neopet(np.content, _x_pwned)
        np.set_referer(referer)
        print(f'Haggling @ {offer}')

        np.post('/haggle.phtml', f'current_offer={offer}', f'x={best_x}', f'y={best_y}')
        if 'I accept your offer' in np.content:
            print('Bought!')
        else:
            print('Not bought :( TODO: See what happened')
    else:
        print(f'No worthy items found. Best was {best[0]} (profit {best_score[2]*100:.1f}% = {best_score[1]})')

    # Learn about unknown items
    for obj_info_id, stock_id, g, brr, image, desc, name, stock, price in items:
        try:
            item_db.get_price(name)
        except item_db.ShopWizardBannedException:
            return neotime.now_nst() + datetime.timedelta(minutes=5)

if __name__ == '__main__':
    #restock(13) # Neopian Pharmacy
    #restock(79) # Brightvale Glaziers
    restock(68) # Collectable Coins
    #restock(14) # Chocolate Factory
    #restock(58) # Post office
    #restock(8) # Collectable cards
