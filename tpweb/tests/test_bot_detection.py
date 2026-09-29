from django.test import SimpleTestCase

from tpweb.services.bot_detection import AUTO_BLOCK_BOT_LABELS, classify_bot


class ClassifyBotTests(SimpleTestCase):
    def test_ai_crawler_user_agents_are_classified(self):
        self.assertEqual(
            classify_bot("Mozilla/5.0 AppleWebKit/537.36 (compatible; ClaudeBot/1.0)"),
            "AI crawler",
        )
        self.assertEqual(classify_bot("GPTBot/1.0"), "AI crawler")

    def test_search_crawler_user_agents_are_classified(self):
        self.assertEqual(
            classify_bot(
                "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            ),
            "Search crawler",
        )

    def test_http_client_user_agents_are_classified(self):
        self.assertEqual(classify_bot("python-requests/2.31"), "HTTP client")

    def test_generic_bot_pattern_is_classified(self):
        self.assertEqual(classify_bot("some-generic-crawler/1.0"), "Generic bot")

    def test_ordinary_browser_user_agent_is_unclassified(self):
        self.assertIsNone(
            classify_bot("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
        )

    def test_empty_user_agent_is_unclassified(self):
        self.assertIsNone(classify_bot(""))
        self.assertIsNone(classify_bot(None))

    def test_auto_block_labels_exclude_http_client_and_search_crawler(self):
        self.assertIn("AI crawler", AUTO_BLOCK_BOT_LABELS)
        self.assertIn("Generic bot", AUTO_BLOCK_BOT_LABELS)
        self.assertNotIn("HTTP client", AUTO_BLOCK_BOT_LABELS)
        self.assertNotIn("Search crawler", AUTO_BLOCK_BOT_LABELS)
