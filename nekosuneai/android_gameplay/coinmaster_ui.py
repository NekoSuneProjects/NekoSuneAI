"""Conservative screen-specific observations for Coin Master - Board Adventure ONLY.\nNot compatible with original Coin Master; call only for com.moonactive.cmboard."""
import re
from decimal import Decimal

import cv2
import numpy as np

from .vision import TemplateMatch


def parse_coins(text):
    if re.fullmatch(r"\s*\d{1,3}(?:[,.]\d{3})+\s*", text):
        return int(re.sub(r"[,.\s]", "", text))
    match = re.fullmatch(r"\s*(\d[\d,]*(?:\.\d+)?)\s*([KMB]?)\s*", text.upper())
    if not match:
        return None
    number, suffix = match.groups()
    if "," in number and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", number):
        return None
    return int(Decimal(number.replace(",", "")) * {"": 1, "K": 1000, "M": 1000000, "B": 1000000000}[suffix])


def _region(frame, box):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    return frame[int(y1*h):int(y2*h), int(x1*w):int(x2*w)]


def _target(frame, name, box, text=None, **details):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    return TemplateMatch(name, .8, int(x1*w), int(y1*h), max(1, int((x2-x1)*w)),
                         max(1, int((y2-y1)*h)), text=text, details=details)


def shows_village_header(frame, matches):
    """Our own village banner: the word alone, centred, high on the screen.

    The number beside it often reads as a separate glyph or not at all, so it
    cannot be required. A raided village names its owner off to the left
    ("Liam's village"), which the centring keeps out.
    """
    h, w = frame.shape[:2]
    return any(re.search(r"\bvillage\b", m.text or "", re.I)
               and m.center[1] < h*.22 and w*.32 < m.center[0] < w*.68
               for m in matches)


def village_targets(frame, matches):
    h, w = frame.shape[:2]
    if not shows_village_header(frame, matches):
        return []
    balances = [parse_coins(m.text) for m in matches if m.text and m.center[0] < w*.5
                and m.center[1] < h*.085]
    balances = [b for b in balances if b is not None]
    balance = max(balances) if balances else None
    result = []
    for index in range(5):
        box = (index/5+.01, .946, (index+1)/5-.01, .989)
        hsv = cv2.cvtColor(_region(frame, box), cv2.COLOR_BGR2HSV)
        green = float(np.mean(cv2.inRange(hsv, (30, 100, 60), (90, 255, 255)) > 0))
        gray = float(np.mean((hsv[:, :, 1] < 55) & (hsv[:, :, 2] > 65)))
        prices = [parse_coins(m.text) for m in matches if m.text
                  and index*w/5 <= m.center[0] < (index+1)*w/5 and m.center[1] > h*.94]
        prices = [p for p in prices if p is not None]
        price = min(prices) if prices else None
        if gray > .45:
            # The game greys out a slot it will not sell right now.
            state = "disabled"
        elif price is not None and balance is not None:
            # Money decides this, not the pill's colour: every village has its
            # own palette, and a theme whose pill is not green would otherwise
            # read as unknown and never be bought.
            state = "affordable" if balance >= price else "unaffordable"
        elif green > .35:
            state = "completed_or_unreadable"
        else:
            state = "unknown"
        result.append(_target(frame, "coinmaster/building_upgrade", box,
                              slot=index+1, state=state, enabled=state == "affordable",
                              price_coins=price, balance_coins=balance,
                              guard_box=[int(index*w/5), int(h*.81), int(w/5), int(h*.19)]))
    result.append(_target(frame, "coinmaster/back_to_board", (.86, .012, .98, .085), enabled=True))
    return result


HAMMER_BOX = (.17, .885, .30, .960)
ENERGY_BOX = (.32, .908, .68, .950)
SPIN_BOX = (.33, .755, .67, .875)
UNWANTED_BUTTONS = ("FRIENDS", "REVENGE")


def _fraction(frame, box, lower, upper):
    hsv = cv2.cvtColor(_region(frame, box), cv2.COLOR_BGR2HSV)
    return float(np.mean(cv2.inRange(hsv, lower, upper) > 0))


def on_board(frame):
    """The board HUD is a tan bar holding a cyan energy pill; no OCR needed."""
    return (_fraction(frame, ENERGY_BOX, (80, 120, 150), (105, 255, 255)) > .45
            and _fraction(frame, (.02, .962, .98, .992), (8, 110, 180), (20, 210, 255)) > .55)


def parse_energy(matches, frame):
    h, w = frame.shape[:2]
    for match in matches:
        if not match.text or not (h*.905 < match.center[1] < h*.955 and w*.3 < match.center[0] < w*.7):
            continue
        found = re.search(r"(\d{1,4})\s*/\s*(\d{1,3})", match.text)
        if not found:
            continue
        # The lightning glyph often reads as a leading digit ("480/80").
        current = int(found.group(1)[-len(found.group(2)):])
        maximum = int(found.group(2))
        if maximum > 0 and current <= maximum:
            return current, maximum
    return None, None


def board_targets(frame, matches):
    if not on_board(frame):
        return []
    h, w = frame.shape[:2]
    energy, energy_max = parse_energy(matches, frame)
    badge = _fraction(frame, (.245, .885, .30, .925), (0, 140, 100), (12, 255, 255))
    spinning = any("stop" == (m.text or "").strip().lower() for m in matches
                   if h*.76 < m.center[1] < h*.87)
    result = [_target(frame, "coinmaster/open_village", HAMMER_BOX, enabled=True,
                      pending_upgrades=badge > .06,
                      interaction="open the village to spend coins on buildings"),
              _target(frame, "coinmaster/spin", SPIN_BOX,
                      enabled=not spinning and energy is not None and energy > 0,
                      spinning=spinning, energy=energy, energy_max=energy_max,
                      interaction="STOP halts a running auto-spin; otherwise it spends 1 energy")]
    result.extend(badge_targets(frame, matches))
    return result


def unwanted_panel(matches):
    """The friends/revenge attack list is opened by mistake; it is never a goal."""
    text = " ".join((m.text or "").lower() for m in matches)
    return "attack your friends" in text or "revenge!" in text


def badge_targets(frame, matches):
    """Locate red numbered badges; aim inside the attached icon, not its counter."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 140, 100), (12, 255, 255)) | cv2.inRange(hsv, (170, 140, 100), (179, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        perimeter = cv2.arcLength(contour, True)
        circularity = 4*np.pi*cv2.contourArea(contour)/max(1, perimeter*perimeter)
        if not (.018*w < bw < .08*w and .8 < bw/bh < 1.25 and circularity > .72
                and cv2.contourArea(contour)/(bw*bh) > .65 and not .09*h < y < .20*h):
            continue
        numbers = [m.text for m in matches if m.text and m.text.isdigit()
                   and x-bw*.3 <= m.center[0] <= x+bw*1.3 and y-bh*.3 <= m.center[1] <= y+bh*1.3]
        white = cv2.inRange(hsv[y:y+bh, x:x+bw], (0, 0, 180), (179, 90, 255))
        if (not numbers and np.mean(white > 0) < .06) or not (x < w*.22 or x > w*.78 or y > h*.87):
            continue
        cx, cy = int(np.clip(x-bw*.4, 0, w-1)), int(np.clip(y+bh*1.7, 0, h-1))
        x1, y1, x2, y2 = max(0, cx-bw), max(0, cy-bh), min(w, cx+bw), min(h, cy+bh)
        result.append(TemplateMatch("coinmaster/numbered_icon", .7, x1, y1,
                                    x2-x1, y2-y1, details={"badge": numbers[0] if numbers else "unread", "meaning": "unknown",
                                                       "opens_panel": True}))
    return result[:8]


def treasure_targets(frame, matches):
    # The red bags with a yellow X are selectable only on the treasure scene.
    if not any("you stole" in (m.text or "").lower() for m in matches):
        return []
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 150, 90), (12, 255, 255)) | cv2.inRange(hsv, (170, 150, 90), (179, 255, 255))
    mask = cv2.inRange(hsv, (18, 130, 150), (38, 255, 255))
    mask[:int(h*.25)] = 0
    mask[int(h*.9):] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (.06*w < bw < .20*w and .65 < bw/bh < 1.5):
            continue
        margin = bw // 2
        surrounding = red[max(0, y-margin):min(h, y+bh+margin), max(0, x-margin):min(w, x+bw+margin)]
        # A real bag is a yellow X sitting on red cloth; gold trophies nearby are not.
        if np.mean(surrounding > 0) < .35:
            continue
        result.append(TemplateMatch("coinmaster/treasure_choice", .75, x, y, bw, bh,
                                    details={"enabled": True}))
    return result[:4]


def shows_merge_event(matches):
    return any("find all items" in (m.text or "").lower() for m in matches)


def merge_exit_target(frame):
    """The merge event is left alone, so the only target is the way out.

    Its X sits higher than a normal popup's, up in the event header, which is
    why the corner is searched from the very top here.
    """
    exit_button = close_button(frame, top=.02)
    if exit_button is None:
        return []
    exit_button.name = "coinmaster/leave_merge"
    exit_button.details = {"enabled": True,
                           "interaction": "leave the merge event; merging is not trained yet"}
    return [exit_button]


def merge_targets(frame, matches):
    if not any("find all items" in (m.text or "").lower() for m in matches):
        return []
    result, appearances = [], []
    for row in range(7):
        for column in range(7):
            box = (.06 + column*.126, .277 + row*.071,
                   .06 + (column+1)*.126, .277 + (row+1)*.071)
            crop = _region(frame, box)
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            background = cv2.inRange(hsv, (75, 30, 100), (105, 200, 255)) > 0
            # Locked orange cells and empty turquoise cells are not drag targets.
            if not .40 < float(np.mean(background)) < .88:
                continue
            thumb = cv2.resize(crop, (40, 40))
            group = None
            for index, previous in enumerate(appearances):
                similarity = cv2.matchTemplate(thumb, previous, cv2.TM_CCOEFF_NORMED)[0, 0]
                if similarity > .93:
                    group = index
                    break
            if group is None:
                group = len(appearances)
                appearances.append(thumb)
            result.append(_target(frame, "coinmaster/merge_item", box,
                                  cell=[row, column], appearance_group=group, enabled=True))
    for item in result:
        group = item.details["appearance_group"]
        item.details["matching_items"] = sum(m.details["appearance_group"] == group for m in result) - 1
    return result


def attack_targets(frame, matches):
    h, w = frame.shape[:2]
    header = " ".join((m.text or "").upper() for m in matches if m.center[1] < h*.18)
    if not ("REVENGE" in header or ("FRIENDS" in header and "VILLAGE" in header)):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 230), (179, 70, 255))
    # Only the village header sits above this; a higher cut clips the topmost
    # reticle, and a clipped ring loses the hole that identifies it.
    white[:int(h*.12)] = 0
    white[int(h*.92):] = 0
    red = cv2.inRange(hsv, (0, 140, 140), (12, 255, 255)) | cv2.inRange(hsv, (170, 140, 140), (179, 255, 255))
    contours, hierarchy = cv2.findContours(white, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    if hierarchy is None:
        return result
    for index, contour in enumerate(contours):
        child = hierarchy[0][index][2]
        if hierarchy[0][index][3] != -1 or child < 0:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (.09*w < bw < .30*w and .75 < bw/bh < 1.3):
            continue
        # A hollow white ring with a red outline distinguishes the attack reticle.
        if cv2.contourArea(contours[child]) < bw*bh*.15:
            continue
        margin = max(3, bw//10)
        border = red[max(0, y-margin):min(h, y+bh+margin), max(0, x-margin):min(w, x+bw+margin)]
        if np.mean(border > 0) < .06:
            continue
        result.append(TemplateMatch("coinmaster/attack_target", .9, x, y, bw, bh,
                                    details={"enabled": True, "interaction": "tap reticle center"}))
    return sorted(result, key=lambda m: (m.y, m.x))[:5]


def result_targets(frame, matches):
    h, w = frame.shape[:2]
    # The shape alone is not enough: a shop offer looks the same and must never
    # be tapped, so the payout wording still has to be there. It is read by a
    # close-up pass over the panel, which only runs on screens shaped like this.
    buttons = dialog_buttons(frame)
    if len(buttons) != 1 or shows_village_header(frame, matches):
        return []
    message = " ".join((m.text or "").lower() for m in matches if m.center[1] > h*.75)
    if not (("attack" in message and "won" in message)
            or ("you stole" in message and "from" in message)):
        return []
    return buttons


def dialog_buttons(frame):
    """Single centred green button on a warm panel: the shape of a dialog."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    panel = hsv[int(h*.82):]
    if np.mean(cv2.inRange(panel, (5, 20, 170), (35, 160, 255)) > 0) < .4:
        return []
    mask = cv2.inRange(hsv, (30, 100, 65), (90, 255, 255))
    mask[:int(h*.86)] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    buttons = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if (.15*w < bw < .55*w and .025*h < bh < .12*h and 2 < bw/bh < 5
                and cv2.contourArea(contour)/(bw*bh) > .65 and .3*w < x+bw/2 < .7*w):
            buttons.append(TemplateMatch("coinmaster/result_continue", .9, x, y, bw, bh,
                                        details={"enabled": True, "interaction": "dismiss completed result dialog"}))
    return buttons


# Wide enough for both payout lines and the button label beneath them.
DIALOG_TEXT_BOX = (0, .74, 1, .97)


def has_dialog_shape(frame):
    return len(dialog_buttons(frame)) == 1


def ignored_buttons(frame, matches):
    """Guard the header buttons that open the friends/revenge list."""
    return [TemplateMatch("coinmaster/ignored_button", m.confidence, m.x, m.y, m.width, m.height,
                          text=m.text,
                          details={"enabled": False,
                                   "interaction": "opens the friends attack list; not part of the goal"})
            for m in matches if m.name == "ocr/button"
            and (m.text or "").strip().upper() in UNWANTED_BUTTONS]


CONTINUE_BOX = (.35, .25, .65, .34)
CONTINUE_PHRASES = ("tap to continue", "tap anywhere", "tap here", "continue")


def continue_target(frame, matches, explicit):
    """Reward and chest screens advance on a tap anywhere; aim at a harmless spot.

    The title strip is used rather than the middle of the screen so that a stray
    tap on an unrecognised dialog cannot land on a confirm or purchase button.
    """
    return _target(frame, "coinmaster/tap_anywhere", CONTINUE_BOX, enabled=True,
                   explicit=explicit,
                   interaction="tap once to dismiss a reward screen that has no button")


def asks_to_continue(matches):
    text = " ".join((m.text or "").lower() for m in matches)
    return any(phrase in text for phrase in CONTINUE_PHRASES)


def ocr_regions(frame):
    """Bands holding text the agent acts on; the rest is timers and decoration.

    On the board every side column is a countdown, and the HUD numbers are read
    by their own close-up passes, so only the centre header is worth the time.
    """
    if on_board(frame):
        # Everything the board needs is colour or a close-up: the energy pill,
        # the spin label and the hammer badge. The rest is countdowns.
        return []
    # A dialog's own pass is NOT a reason to skip this band: a village whose
    # cards happen to show one centred green pill looks just like a dialog, and
    # skipping the band left its header unread and the whole screen unusable.
    # One pass only: a second band costs another detection sweep, and the text
    # it would catch is already covered by the price and panel crops.
    return [(0, 0, 1, .40)]


# Real money, in any storefront locale: a currency symbol, an ISO code or a
# written currency word next to an amount, an amount with exactly two decimals,
# or a word that starts a purchase. Coin prices always carry a K/M/B suffix and
# coin counts are grouped in threes, so neither can match.
CURRENCY_SYMBOLS = "£$€¥₹₩₽₺₪฿₫₴₦₼₾"
CURRENCY_CODES = (
    "USD CAD AUD NZD EUR GBP CHF JPY CNY RMB HKD TWD KRW SGD INR IDR MYR PHP "
    "THB VND BRL MXN ARS CLP COP PEN ZAR NGN KES EGP AED SAR ILS TRY RUB UAH "
    "PLN CZK HUF RON SEK NOK DKK ISK BGN HRK"
).split()
# How prices are written out locally, e.g. "kr 49.00" or "49,99 zł".
CURRENCY_WORDS = ("kr", "kn", "zł", "zl", "kč", "kc", "ft", "lei", "лв",
                  "rp", "rm", "grn", "руб")
PURCHASE_WORDS = ("buy", "pay", "purchase", "subscribe", "checkout", "order")

_NAMES = "|".join(CURRENCY_CODES + list(CURRENCY_WORDS))
MONEY = re.compile(
    "[" + CURRENCY_SYMBOLS + "]" + r"\s*\d"
    + r"|\d\s*[" + CURRENCY_SYMBOLS + "]"
    + r"|(?:" + _NAMES + r")\s*[" + CURRENCY_SYMBOLS + r"]?\s*\d"
    + r"|\d\s*(?:" + _NAMES + r")(?![A-Za-z])"
    # An amount with exactly two decimals, not part of a longer number and not
    # a K/M/B coin price: the shape every storefront uses for a real price.
    + r"|(?<![\d.,])\d{1,4}[.,]\d{2}(?![\d.,KMB])"
    + r"|^\s*(?:" + "|".join(PURCHASE_WORDS) + r")(?![a-z])",
    re.I)


def looks_like_money(text):
    return bool(text) and bool(MONEY.search(text))


def purchase_guards(frame, matches):
    """Never let a tap reach a real-money button, whatever else is on screen."""
    h, w = frame.shape[:2]
    guards = []
    for match in matches:
        if not looks_like_money(match.text) or match.name.startswith("coinmaster/"):
            continue
        # The price label sits inside a larger button; guard the whole button.
        pad_x, pad_y = int(match.width*.8), int(match.height*.9)
        x, y = max(0, match.x-pad_x), max(0, match.y-pad_y)
        guards.append(TemplateMatch(
            "coinmaster/purchase_button", match.confidence, x, y,
            min(w-x, match.width+2*pad_x), min(h-y, match.height+2*pad_y), text=match.text,
            details={"enabled": False,
                     "interaction": "real-money purchase; the person decides this, never the agent"}))
    return guards


FREE_BUTTON = re.compile(r"^\s*(collect|claim|free|get\s+it|redeem)", re.I)


def free_reward_buttons(frame, matches):
    """A COLLECT/CLAIM button, but only when nothing on screen has a price.

    A popup that gives something away is worth taking; the moment a real-money
    amount appears anywhere on it, the whole screen is left for the person.
    """
    if any(looks_like_money(m.text) for m in matches):
        return []
    result = []
    for match in matches:
        if match.name != "ocr/button" or not FREE_BUTTON.match(match.text or ""):
            continue
        result.append(TemplateMatch("coinmaster/collect_free", match.confidence,
                                    match.x, match.y, match.width, match.height,
                                    text=match.text,
                                    details={"enabled": True,
                                             "interaction": "collect a free reward"}))
    return result[:2]


def close_button(frame, top=.10):
    """The round red X that closes an offer or event popup.

    Deliberately strict: it may only pre-empt the rest of the screen when it is
    clearly a modal's close button, not the village's red back arrow or a badge.
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = (cv2.inRange(hsv, (0, 120, 90), (10, 255, 255))
           | cv2.inRange(hsv, (170, 120, 90), (179, 255, 255)))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (.05*w < bw < .13*w and .85 < bw/bh < 1.2):
            continue
        perimeter = cv2.arcLength(contour, True)
        if 4*np.pi*cv2.contourArea(contour)/max(1, perimeter*perimeter) < .8:
            continue
        if cv2.contourArea(contour)/(bw*bh) < .7:
            continue
        centre_x, centre_y = (x+bw/2)/w, (y+bh/2)/h
        # Top-right of a panel, and below the header where the back arrow lives.
        if not (centre_x > .55 and top < centre_y < .75):
            continue
        inner = hsv[y+bh//4:y+3*bh//4, x+bw//4:x+3*bw//4]
        if np.mean(cv2.inRange(inner, (0, 0, 200), (179, 60, 255)) > 0) < .45:
            continue
        return TemplateMatch("coinmaster/close_popup", .85, x, y, bw, bh,
                             details={"enabled": True,
                                      "interaction": "close this popup; it is not part of the goal"})
    return None


def suppress_matches(matches):
    """Drop the header buttons that only open the friends attack list."""
    return [m for m in matches
            if not (m.name == "ocr/button"
                    and ((m.text or "").strip().upper() in UNWANTED_BUTTONS
                         or looks_like_money(m.text)))]


def detect_ui(frame, matches):
    h, w = frame.shape[:2]
    if not 1.4 < h/w < 2.2:
        return []
    money = purchase_guards(frame, matches)
    free = free_reward_buttons(frame, matches)
    popup = close_button(frame)
    if popup is not None:
        # An offer or event popup covers whatever is behind it, so nothing behind
        # it can be acted on. Take a free reward if it offers one, else close it.
        return free + [popup] + money
    scene = _detect_scene(frame, matches)
    if scene and scene[0].name in ("coinmaster/result_continue", "coinmaster/unwanted_panel"):
        return scene + money
    guards = ignored_buttons(frame, matches) + money + free
    if asks_to_continue(matches) and not scene:
        return [continue_target(frame, matches, True)] + guards
    if not scene and not guards:
        return [continue_target(frame, matches, False)]
    return scene + guards


def _detect_scene(frame, matches):
    h, w = frame.shape[:2]
    results = result_targets(frame, matches)
    if results:
        return results
    if unwanted_panel(matches):
        return [_target(frame, "coinmaster/unwanted_panel", (.06, .2, .94, .95),
                        enabled=False, close_with="back",
                        interaction="close this friends list with the back key")]
    attacks = attack_targets(frame, matches)
    if attacks:
        return attacks
    village = village_targets(frame, matches)
    if village:
        return village
    if shows_merge_event(matches):
        return merge_exit_target(frame)
    if any("you stole" in (m.text or "").lower() for m in matches):
        return treasure_targets(frame, matches)
    return board_targets(frame, matches)
