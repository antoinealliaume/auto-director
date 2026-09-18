import os
import unittest

from app import tiktok_oauth as oauth
from app import tiktok_posting as posting


class TikTokSecurityTests(unittest.TestCase):
    def setUp(self):
        self.old=os.environ.get('TIKTOK_TOKEN_ENCRYPTION_KEY')
        os.environ['TIKTOK_TOKEN_ENCRYPTION_KEY']='unit-test-secret-that-never-leaves-ci'
    def tearDown(self):
        if self.old is None:os.environ.pop('TIKTOK_TOKEN_ENCRYPTION_KEY',None)
        else:os.environ['TIKTOK_TOKEN_ENCRYPTION_KEY']=self.old

    def test_token_encryption_round_trip(self):
        value='act.secret-example'
        encrypted=oauth.encrypt(value)
        self.assertNotIn(value,encrypted)
        self.assertEqual(oauth.decrypt(encrypted),value)

    def test_pull_token_is_asset_scoped(self):
        token=posting.make_pull_token('asset-a')
        self.assertTrue(posting.verify_pull_token(token,'asset-a'))
        self.assertFalse(posting.verify_pull_token(token,'asset-b'))
        self.assertFalse(posting.verify_pull_token(token+'x','asset-a'))

    def test_utf16_title_limit_handles_emoji(self):
        text='a'*2199+'😀'+'z'
        out=posting._truncate_utf16(text,2200)
        self.assertEqual(out,'a'*2199)
        self.assertLessEqual(len(out.encode('utf-16-le'))//2,2200)


if __name__=='__main__':
    unittest.main()
