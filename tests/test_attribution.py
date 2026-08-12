"""Attribution tests, written against titles in the shape both platforms emit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bridge.normalize.attribution import (  # noqa: E402
    attribute_brand,
    attribute_oem,
    resolve_product_type,
)


def brand_of(title: str, category: str | None = "notebook", **kw) -> str:
    ptype, is_component = resolve_product_type(category, title)
    return attribute_brand(title, is_component=is_component, **kw).brand


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}\n        got={got!r} want={want!r}"
          if not ok else f"  PASS  {label}")
    return ok


results: list[bool] = []

print("\n=== Rule 1: discrete GPU must not attribute a system ===")
results += [
    check(
        "Ryzen laptop with NVIDIA GPU -> amd",
        brand_of("Lenovo Legion 5 Gaming Laptop AMD Ryzen 7 7735HS NVIDIA GeForce RTX 4060 16GB"),
        "amd",
    ),
    check(
        "Intel laptop with NVIDIA GPU -> intel",
        brand_of("ASUS ROG Strix G16 Gaming Laptop Intel Core i7-13650HX GeForce RTX 4070"),
        "intel",
    ),
    check(
        "Intel laptop with AMD Radeon graphics -> intel",
        brand_of("HP Victus 15 Intel Core i5-13420H AMD Radeon RX 6550M 8GB Gaming Notebook"),
        "intel",
    ),
    check(
        "standalone NVIDIA card in gpu category -> nvidia",
        brand_of("GIGABYTE GeForce RTX 4070 SUPER WINDFORCE OC 12G Graphics Card", "gpu"),
        "nvidia",
    ),
    check(
        "standalone Radeon card -> amd",
        brand_of("Sapphire PULSE AMD Radeon RX 7800 XT 16GB GDDR6 Graphics Card", "gpu"),
        "amd",
    ),
]

print("\n=== Rule 1b: the brand-name FALLBACK must respect the same rule ===")
results += [
    check(
        "laptop with no CPU in title must NOT become nvidia",
        brand_of("Lenovo Legion Pro 7i Gaming Laptop NVIDIA GeForce RTX 4080 32GB DDR5 1TB"),
        "other",
    ),
    check(
        "desktop with no CPU in title must NOT become nvidia",
        brand_of("ASUS ROG Strix Gaming Desktop NVIDIA GeForce RTX 4070 32GB", "desktop"),
        "other",
    ),
    check(
        "but a graphics card still attributes to nvidia",
        brand_of("GIGABYTE GeForce RTX 4070 SUPER WINDFORCE OC 12G Graphics Card", "gpu"),
        "nvidia",
    ),
    check(
        "CPU present still wins over the GPU vendor",
        brand_of("Lenovo Legion Pro 7i Intel Core i9-14900HX NVIDIA GeForce RTX 4080"),
        "intel",
    ),
]

print("\n=== Rule 2: Apple tokens need Apple context ===")
results += [
    check(
        "M.2 slot must not read as Apple M2",
        brand_of("MSI Katana 15 Intel Core i7-13620H 1TB M.2 NVMe SSD RTX 4060"),
        "intel",
    ),
    check(
        "genuine MacBook -> apple",
        brand_of('Apple MacBook Pro 14" M4 Pro chip 24GB 512GB SSD'),
        "apple",
    ),
    check(
        "iPad with M-series -> apple",
        brand_of('Apple iPad Pro 13" M4 chip 256GB Wi-Fi', "tablet"),
        "apple",
    ),
]

print("\n=== Processor line specificity (most-specific-first) ===")
for title, want_line in [
    ("Dell XPS 14 Intel Core Ultra 7 155H 32GB", "Core Ultra 7"),
    ("Acer Swift Go Intel Core Ultra 5 125H", "Core Ultra 5"),
    ("Lenovo LOQ Intel Core i7-13650HX", "Core i7"),
    ("ASUS Zenbook Snapdragon X Elite X1E-78-100", "Snapdragon X Elite"),
    ("HP OmniBook X Snapdragon X Plus", "Snapdragon X Plus"),
    ("ASUS ROG Zephyrus AMD Ryzen AI 9 HX 370", "Ryzen AI"),
    ("Alienware m18 AMD Ryzen 9 7945HX3D", "Ryzen 9"),
]:
    ptype, is_comp = resolve_product_type("notebook", title)
    got = attribute_brand(title, is_component=is_comp).processor_line
    results.append(check(f"{title[:44]:44s} -> {want_line}", got, want_line))

print("\n=== Product type resolution ===")
results += [
    check(
        "bare CPU cross-listed in PC Gamer category -> cpu/component",
        resolve_product_type("desktop", "Processador AMD Ryzen 5 5600X 3.7GHz Box"),
        ("cpu", True),
    ),
    check(
        "GPU cross-listed in desktop category -> gpu/component",
        resolve_product_type("desktop", "Placa de Video RTX 4060 Ti 8GB GDDR6"),
        ("gpu", True),
    ),
    check(
        "genuine prebuilt stays desktop",
        resolve_product_type("desktop", "Computador Gamer PC Ryzen 5 5600G 16GB SSD 480GB"),
        ("desktop", False),
    ),
]

print("\n=== OEM attribution (independent of brand) ===")
for title, want_oem in [
    ("Lenovo Legion 5 AMD Ryzen 7", "lenovo"),
    ("Alienware m18 R2 Intel Core i9", "dell"),
    ("HP OMEN 16 Intel Core i7", "hp"),
    ("ASUS TUF Gaming A15 Ryzen 7", "asus"),
    ("Acer Predator Helios Neo 16", "acer"),
    ("MSI Raider GE78 HX", "msi"),
    ('Apple MacBook Air 15" M3', "apple"),
]:
    ptype, is_comp = resolve_product_type("notebook", title)
    got = attribute_oem(title, is_component=is_comp).oem
    results.append(check(f"{title[:44]:44s} -> {want_oem}", got, want_oem))

print("\n=== OEM is null for components, not 'unknown' ===")
results += [
    check(
        "boxed CPU has no OEM",
        attribute_oem("Processador AMD Ryzen 5 5600X Box", is_component=True).oem,
        None,
    ),
    check(
        "board partner is not an OEM",
        attribute_oem("GIGABYTE GeForce RTX 4070 WINDFORCE", is_component=False).oem,
        None,
    ),
]

print("\n=== Spec-table rescue (title omits processor) ===")
_ptype, _ic = resolve_product_type("notebook", "Notebook Gamer 16GB 512GB SSD")
_attr = attribute_brand(
    "Notebook Gamer 16GB 512GB SSD",
    is_component=_ic,
    spec_text="Processador: AMD Ryzen 5 7535HS Memoria: 16GB",
)
results += [
    check("brand rescued from specs", _attr.brand, "amd"),
    check("lower confidence than a title match", _attr.confidence < 0.95, True),
]

print("\n=== Unattributed products land in 'other', not dropped ===")
results.append(check("no chip mentioned -> other", brand_of("Gaming Laptop Backpack 17 inch"), "other"))

passed, total = sum(results), len(results)
print(f"\n{'=' * 56}\n  {passed}/{total} passed\n{'=' * 56}")
sys.exit(0 if passed == total else 1)
