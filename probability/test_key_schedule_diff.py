"""Direct Monte-Carlo test for a Splight related-key schedule difference.

This test invokes the executable Splight key schedule.  It does not use the
bit-level MILP model, so it can be used to check whether a MILP-selected round
key difference is reachable with non-zero probability.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path


IMPLEMENT_DIR = Path(__file__).resolve().parents[3] / "Splight_implement" / "implement_py"
sys.path.insert(0, str(IMPLEMENT_DIR))

from enc import SplightParams, key_schedule, nibbles_to_hex  # noqa: E402


DEFAULT_MASTER_KEY_DIFF = "00000000000000002000000000020002"


def parse_size(value: str) -> int:
    value = value.strip().lower()
    if "^" in value:
        base, exponent = value.split("^", 1)
        return int(base, 0) ** int(exponent, 0)
    return int(value, 0)


def round_key_difference(key0: int, master_key_diff: int, round_index: int, params: SplightParams) -> str:
    key1 = key0 ^ master_key_diff
    round_keys0 = key_schedule(f"{key0:032X}", params)
    round_keys1 = key_schedule(f"{key1:032X}", params)
    difference = int(nibbles_to_hex(round_keys0[round_index]), 16) ^ int(nibbles_to_hex(round_keys1[round_index]), 16)
    return f"{difference:08X}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Direct related-key round-key difference experiment for Splight.")
    parser.add_argument("--master-key-diff", default=DEFAULT_MASTER_KEY_DIFF, help="128-bit hexadecimal master-key difference.")
    parser.add_argument("--round", type=int, default=5, dest="round_index", help="Zero-based round-key index.")
    parser.add_argument("--samples", default="2^20", help="Number of random key pairs, e.g. 2^20.")
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--targets", nargs="*", default=["00000000", "C0000000"], help="32-bit round-key differences to report.")
    parser.add_argument("--top", type=int, default=16, help="Number of most common values to print.")
    args = parser.parse_args()

    master_key_diff = int(args.master_key_diff, 16)
    if master_key_diff.bit_length() > 128:
        raise ValueError("--master-key-diff must fit in 128 bits.")
    if not 0 <= args.round_index < SplightParams().rounds:
        raise ValueError("--round is outside the Splight key schedule range.")

    samples = parse_size(args.samples)
    rng = random.Random(args.seed)
    params = SplightParams()
    counts: Counter[str] = Counter()
    for _ in range(samples):
        counts[round_key_difference(rng.getrandbits(128), master_key_diff, args.round_index, params)] += 1

    print("Related-key schedule probability test")
    print(f"master key diff : {master_key_diff:032X}")
    print(f"round key index : {args.round_index}")
    print(f"samples         : {samples} (2^{samples.bit_length() - 1})" if samples & (samples - 1) == 0 else f"samples         : {samples}")
    print(f"seed            : {args.seed}")
    for target in args.targets:
        target = f"{int(target, 16):08X}"
        count = counts[target]
        print(f"RK_{args.round_index} = {target}: count={count}, probability={count / samples:.12g}")
    print("Most common observed differences:")
    for value, count in counts.most_common(args.top):
        print(f"  {value}: {count} ({count / samples:.12g})")
    print(f"distinct values : {len(counts)}")


if __name__ == "__main__":
    main()
