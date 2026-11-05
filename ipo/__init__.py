"""Indian mainboard IPO analyzer."""
import re


def num(s):
    """First number in a string like '₹1,269.83 Cr' or '63.89x'; None if there is none."""
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", "").replace("−", "-"))
    return float(m.group()) if m else None
