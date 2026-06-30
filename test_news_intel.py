import json
import os
import tempfile
import unittest

import mundial_2026 as mdl
import news_intel


class NewsIntelTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_state_file = mdl.STATE_FILE
        self.orig_seen_file = news_intel.SEEN_ARTICLES_FILE
        mdl.STATE_FILE = os.path.join(self.tmpdir.name, "wc2026_state.json")
        news_intel.SEEN_ARTICLES_FILE = os.path.join(self.tmpdir.name, "news_seen_articles.json")
        news_intel._pending_items.clear()
        news_intel._seen_articles.clear()
        mdl.TEAM_FORM["France"] = 0

    def tearDown(self):
        mdl.TEAM_FORM["France"] = 0
        news_intel._pending_items.clear()
        news_intel._seen_articles.clear()
        mdl.STATE_FILE = self.orig_state_file
        news_intel.SEEN_ARTICLES_FILE = self.orig_seen_file
        self.tmpdir.cleanup()

    def test_high_confidence_form_item_updates_and_persists_team_form(self):
        result = news_intel._apply_item({
            "type": "form",
            "team": "France",
            "direction": "+1",
            "detail": "France impressed in training",
        })

        self.assertEqual(mdl.TEAM_FORM["France"], 1)
        self.assertIn("France", result)
        with open(mdl.STATE_FILE) as f:
            saved = json.load(f)
        self.assertEqual(saved["team_form"]["France"], 1)

    def test_medium_confidence_route_uses_short_pending_callback_key(self):
        sent = {}
        original_notify = news_intel._notify_with_buttons

        def fake_notify(text, buttons):
            sent["text"] = text
            sent["buttons"] = buttons

        news_intel._notify_with_buttons = fake_notify
        try:
            item = {
                "type": "form",
                "team": "France",
                "direction": "-1",
                "detail": "France looked fatigued",
                "confidence": 0.6,
            }
            news_intel._route_item(item, "BBC Sport", "https://example.com/france")
        finally:
            news_intel._notify_with_buttons = original_notify

        apply_data = sent["buttons"][0][0]["callback_data"]
        ignore_data = sent["buttons"][0][1]["callback_data"]
        self.assertTrue(apply_data.startswith("news_apply||"))
        self.assertTrue(ignore_data.startswith("news_ignore||"))
        self.assertLessEqual(len(apply_data.encode()), 64)
        self.assertLessEqual(len(ignore_data.encode()), 64)

        key = apply_data.split("||", 1)[1]
        self.assertEqual(news_intel.get_pending_item(key), item)

    def test_seen_articles_survive_process_restart(self):
        news_intel._seen_articles.update({"article-a", "article-b"})
        news_intel._save_seen_articles()

        news_intel._seen_articles.clear()
        news_intel._load_seen_articles()

        self.assertEqual(news_intel._seen_articles, {"article-a", "article-b"})


if __name__ == "__main__":
    unittest.main()
