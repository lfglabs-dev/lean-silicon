import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "gds.yaml"


class ViewerWorkflowTest(unittest.TestCase):
    def test_pages_upload_finishes_before_deployment_job(self):
        workflow = WORKFLOW.read_text()
        build = workflow.index("  viewer-build:")
        deploy = workflow.index("  viewer:\n", build)
        self.assertLess(build, deploy)
        self.assertIn("needs: viewer-build", workflow[deploy:])
        self.assertIn("actions/upload-pages-artifact@7b1f4a", workflow[build:deploy])
        self.assertNotIn("actions/deploy-pages@", workflow[build:deploy])
        self.assertIn("actions/deploy-pages@cd2ce8f", workflow[deploy:])
        self.assertNotIn("TinyTapeout/tt-gds-action/viewer@", workflow)


if __name__ == "__main__":
    unittest.main()
