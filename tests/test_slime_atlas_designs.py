import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGNS = (ROOT / "slime-atlas-3d" / "v4" / "designs.js").read_text(encoding="utf-8")


class SlimeAtlasDesignTests(unittest.TestCase):
    def test_vertex_evolution_preserves_same_facial_region_as_materials(self):
        vertex = DESIGNS.split("export const designVertexUniforms = `", 1)[1].split("`;", 1)[0]
        fragment = DESIGNS.split("export const designFragmentUniforms = `", 1)[1].split("`;", 1)[0]
        predicate = "uPart>2.5&&uPart<5.5&&!(abs(p.x)>.65&&p.z<.25)"

        self.assertIn(f"bool facial={predicate};", vertex)
        self.assertIn("if(facial) return p;", vertex)
        self.assertIn(f"bool facial={predicate};", fragment)
        self.assertLess(vertex.index("if(facial) return p;"), vertex.index("if(uDesign==1||uDesign==2)"))


if __name__ == "__main__":
    unittest.main()
