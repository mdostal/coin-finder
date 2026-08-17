import json
import sys
from pathlib import Path

from bip_utils import (
    Bip44,
    Bip44Changes,
    Bip44Coins,
    Bip49,
    Bip49Coins,
    Bip84,
    Bip84Coins,
    Bip39SeedGenerator,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.bitcoin import BitcoinService
from services.ethereum import EthereumService
from services.litecoin import LitecoinService
from tools.check_wallet_balances import _check_balance_with_retries

# Bounded v1 scheme set -- BIP44/49/84 for Bitcoin (the three common modern
# address formats) plus BIP44 for Ethereum and Litecoin. A more exhaustive
# "deep dive" mode covering exotic old-wallet schemes is a deliberate
# follow-up epic, not attempted here.
SCHEMES = [
    ("BIP44", "Bitcoin", Bip44, Bip44Coins.BITCOIN),
    ("BIP49", "Bitcoin", Bip49, Bip49Coins.BITCOIN),
    ("BIP84", "Bitcoin", Bip84, Bip84Coins.BITCOIN),
    ("BIP44", "Ethereum", Bip44, Bip44Coins.ETHEREUM),
    ("BIP44", "Litecoin", Bip44, Bip44Coins.LITECOIN),
]

SERVICES_BY_COIN = {
    "Bitcoin": BitcoinService,
    "Ethereum": EthereumService,
    "Litecoin": LitecoinService,
}


def derive_candidate_addresses(phrase, num_addresses=5):
    """
    Derive external-chain (account=0, change=0) addresses for indices
    0..num_addresses-1 across the bounded v1 scheme set. Never computes or
    returns a private key / WIF -- addresses only.

    :return: [{"scheme": str, "coin": str, "index": int, "address": str}, ...]
    """
    seed_bytes = Bip39SeedGenerator(phrase).Generate()
    derived = []

    for scheme_name, coin_name, bip_class, coin_enum in SCHEMES:
        account = bip_class.FromSeed(seed_bytes, coin_enum).Purpose().Coin().Account(0)
        change = account.Change(Bip44Changes.CHAIN_EXT)
        for index in range(num_addresses):
            address = change.AddressIndex(index).PublicKey().ToAddress()
            derived.append({
                "scheme": scheme_name,
                "coin": coin_name,
                "index": index,
                "address": address,
            })

    return derived


def load_service_for_coin(coin_name):
    """
    Instantiate the balance-check service for coin_name, returning None
    (rather than raising) when the service can't be loaded -- e.g. a missing
    API key. Mirrors check_wallet_balances.py::load_service's graceful
    degradation.
    """
    service_class = SERVICES_BY_COIN.get(coin_name)
    if service_class is None:
        return None
    try:
        return service_class()
    except Exception as e:
        print(f"Service unavailable for {coin_name}: {e}")
        return None


def check_derived_balances(derived):
    """
    Check balance for every derived address, reusing the existing retry
    helper (no duplicated retry logic). Adds a "balance" key to each entry.
    """
    service_cache = {}
    for entry in derived:
        coin = entry["coin"]
        if coin not in service_cache:
            service_cache[coin] = load_service_for_coin(coin)
        service = service_cache[coin]

        if service is None:
            entry["balance"] = None
            continue

        entry["balance"] = _check_balance_with_retries(service, entry["address"])

    return derived


def match_phrases(phrases, num_addresses=5):
    """
    Derive and balance-check every phrase in phrases.
    :return: {phrase: [derived+balance dicts]}
    """
    return {
        phrase: check_derived_balances(derive_candidate_addresses(phrase, num_addresses))
        for phrase in phrases
    }


def load_phrases_from_file(path):
    """
    Accepts either find_seed_phrases.py's output JSON shape
    ({file_path: [{"phrase": ...}, ...]}) or a plain newline-separated text
    file of phrases. Returns a deduplicated flat list, order-preserving.
    """
    with open(path, "r") as f:
        content = f.read()

    phrases = []
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            for candidates in data.values():
                for candidate in candidates:
                    phrases.append(candidate["phrase"])
        else:
            raise ValueError("not the expected dict shape")
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        phrases = [line.strip() for line in content.splitlines() if line.strip()]

    seen = set()
    deduped = []
    for phrase in phrases:
        if phrase not in seen:
            seen.add(phrase)
            deduped.append(phrase)
    return deduped


def render_match_report(results):
    """
    Phrase text appears only for phrases with at least one non-zero-balance
    derived address (the actual finding). Non-finding phrases are reported by
    input index only -- phrase text is not gratuitously repeated.
    """
    lines = ["# Seed Phrase Match Report", "", "Bounded v1 scheme coverage: BIP44/BIP49/BIP84 (Bitcoin), BIP44 (Ethereum, Litecoin). Exotic old-wallet schemes are not covered -- see the deep-dive follow-up epic.", ""]

    for index, (phrase, entries) in enumerate(results.items()):
        findings = [e for e in entries if e.get("balance")]
        if findings:
            lines.append(f"## Phrase #{index}: FOUND BALANCE")
            lines.append(f"Phrase: `{phrase}`")
            for f in findings:
                lines.append(
                    f"- {f['coin']} ({f['scheme']}, index {f['index']}): `{f['address']}` -- {f['balance']} "
                )
        else:
            lines.append(f"## Phrase #{index}: no balance found across {len(entries)} address(es) checked")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Derive addresses from candidate seed phrases (bounded scheme set) and check each for a balance."
    )
    parser.add_argument("phrases_file", help="File of candidate phrases (find_seed_phrases.py JSON output, or plain newline-separated text). Never pass a phrase as a CLI argument.")
    parser.add_argument("output_file", help="Output JSON file for match results.")
    parser.add_argument("--num-addresses", type=int, default=5, help="Addresses to check per scheme (default 5).")
    args = parser.parse_args()

    phrases = load_phrases_from_file(args.phrases_file)
    results = match_phrases(phrases, num_addresses=args.num_addresses)

    with open(args.output_file, "w") as f:
        json.dump(results, f, indent=4)

    report_file = args.output_file.rsplit(".", 1)[0] + ".md"
    with open(report_file, "w") as f:
        f.write(render_match_report(results))

    # Security: never print phrase text to stdout/logs.
    total_findings = sum(1 for entries in results.values() if any(e.get("balance") for e in entries))
    print(f"Checked {len(phrases)} phrase(s). {total_findings} produced a non-zero balance. See {report_file}.")
