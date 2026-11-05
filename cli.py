"""Terminal version.  python cli.py            -> list mainboard IPOs
                     python cli.py <name>     -> full analysis of one IPO"""
import sys

from ipo import market, pipeline

sys.stdout.reconfigure(encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        for r in market.list_ipos():
            gmp = f"{r['gmp_pct']:.1f}%" if r["gmp_pct"] is not None else "--"
            print(f"{r['status']:9} {r['name'][:40]:40} GMP {gmp:>7}  sub {r['subscription'] or '--'}x  [{r['slug']}]")
        return
    ipo = pipeline.find(" ".join(a for a in sys.argv[1:] if not a.startswith("--")))
    if not ipo:
        sys.exit("IPO not found. Run without arguments to see the list.")
    res = pipeline.analyze(ipo, transcripts="--fast" not in sys.argv)
    print(f"\n{ipo['name']}  ({ipo['status']}, price ₹{ipo['price']})")
    for key, title in (("listing", "LISTING GAIN"), ("long_term", "LONG TERM")):
        s = res["scores"][key]
        print(f"\n=== {title}: {s['label']}  score {s['score']}/100  confidence {s.get('confidence')} ({s.get('coverage')}% data)")
        for c in s["components"]:
            print(f"  {c['name']:24} {c['score'] if c['score'] is not None else 'n/a':>4}  (weight {c['weight']})")
            for sign, text in c["notes"]:
                print(f"      {sign} {text}")
        for sev, text in s["flags"]:
            print(f"  {'RED FLAG' if sev else 'caution'}: {text}")
    p = res.get("prediction")
    if p:
        print("\n=== PREDICTIONS (learned from past IPOs)")
        if p["gain_mid"] is not None:
            print(f"  Expected listing gain {p['gain_mid']:+.1f}% (likely {p['gain_low']:+.0f}% to {p['gain_high']:+.0f}%)")
            print(f"  Chance it lists above issue price {p['p_positive'] * 100:.0f}%")
        if p["p_beat"] is not None:
            print(f"  Chance to beat other IPOs of its quarter over time {p['p_beat'] * 100:.0f}%")
        if p.get("mood_median") is not None:
            print(f"  IPO market mood: last 10 listings median {p['mood_median']:+.1f}%, {p['mood_positive']:.0f}% positive")
    for name in ("x", "instagram"):
        s = res["sentiment"].get(name)
        if s and s["n"]:
            print(f"  {name}: {s['n']} posts, tone {s['score']:+.2f}")
    for e in res["errors"]:
        print("  [source error]", e)
    print("\nResearch aid only, not investment advice.")


if __name__ == "__main__":
    main()
