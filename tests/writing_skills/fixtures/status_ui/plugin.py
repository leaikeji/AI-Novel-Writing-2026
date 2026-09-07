"""Public extension only; cannot be installed outside the disposable S58 host."""
import os
from qwenpaw.pawapp import PawApp

pawapp = PawApp(name="S58 fake UI", app_id="s58-method-ui")


class FixturePlugin:
    def register(self, api):
        if not os.environ.get("AI_NOVEL_DATABASE_URL", "").endswith("@postgres:5432/ai_novel_s58_test"):
            raise RuntimeError("S58 fixture requires its disposable environment")
        pawapp.register(api)


plugin = FixturePlugin()
