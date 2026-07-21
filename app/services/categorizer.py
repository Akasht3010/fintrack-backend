import re

# Checked in order — first match wins, so put more specific keywords
# (e.g. a named food delivery app) before generic ones.
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("food", [
        "swiggy", "zomato", "dominos", "domino's", "mcdonald", "kfc", "starbucks",
        "pizza", "cafe", "restaurant", "eatery", "biryani", "burger", "dunzo",
        "eatsure", "faasos"
    ]),
    ("transport", [
        "uber", "ola", "rapido", "railway", "irctc", "metro", "petrol", "diesel",
        "fuel", "parking", "toll", "fastag", "indigo", "spicejet", "vistara",
        "airindia", "redbus", "ridefare"
    ]),
    ("shopping", [
        "amazon", "flipkart", "myntra", "ajio", "meesho", "zepto", "blinkit",
        "bigbasket", "grofers", "nykaa", "marketplace", "mall", "reliance digital"
    ]),
    ("entertainment", [
        "netflix", "spotify", "hotstar", "prime video", "bookmyshow", "pvr",
        "inox", "googleplay", "playstore", "steam", "audible", "sonyliv"
    ]),
    ("utilities", [
        "electricity", "airtel", "jio", "vodafone", "vi postpaid", "broadband",
        "wifi", "recharge", "gas bill", "water bill", "dth", "tatasky", "act fibernet"
    ]),
    ("rent", [
        "rent", "landlord", "housing society", "nobroker"
    ]),
    ("health", [
        "pharmacy", "hospital", "clinic", "apollo", "medplus", "diagnostic",
        "medical", "practo", "1mg", "netmeds"
    ]),
    ("subscriptions", [
        "subscription", "membership", "prime membership"
    ]),
    ("transfer", [
        "neft", "imps", "rtgs", "fund transfer", "money transfer"
    ]),
]


def categorize_merchant(merchant: str, description: str = "") -> str:
    """
    Best-effort category guess from a merchant name (and optionally a
    description), matched against known keywords. Falls back to "other"
    when nothing matches rather than guessing wrong.
    """
    text = f"{merchant} {description}".lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    for category, keywords in CATEGORY_KEYWORDS:
        for keyword in keywords:
            if keyword in text:
                return category

    return "other"
