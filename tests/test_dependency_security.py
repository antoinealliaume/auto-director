import re
import unittest
from importlib.metadata import version


def numeric_version(package: str) -> tuple[int, int, int]:
    parts = [int(x) for x in re.findall(r"\d+", version(package))[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class DependencySecurityFloorTests(unittest.TestCase):
    def test_fastapi_release_supports_patched_starlette(self):
        # 0.139.2 accepts Starlette 1.x and avoids the cache regression reported in 0.140-0.141.
        self.assertGreaterEqual(numeric_version("fastapi"), (0, 139, 2))

    def test_starlette_resolves_above_all_reported_fixes(self):
        self.assertGreaterEqual(numeric_version("starlette"), (1, 3, 1))

    def test_cryptography_resolves_above_all_reported_fixes(self):
        self.assertGreaterEqual(numeric_version("cryptography"), (50, 0, 0))


if __name__ == "__main__":
    unittest.main()
