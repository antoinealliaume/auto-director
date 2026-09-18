import io
import os
import unittest
from unittest.mock import patch

import storage_backend as s


class FakeBody(io.BytesIO):
    pass


class FakeS3:
    def __init__(self):
        self.objects={}
    def put_object(self,**kw):
        self.objects[kw['Key']]=bytes(kw['Body'])
    def get_object(self,**kw):
        payload=self.objects[kw['Key']]
        spec=kw.get('Range')
        if spec:
            a,b=spec.replace('bytes=','').split('-',1);payload=payload[int(a):int(b)+1]
        return {'Body':FakeBody(payload)}
    def delete_object(self,**kw):
        self.objects.pop(kw['Key'],None)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.old={k:os.environ.get(k) for k in (
            'OBJECT_STORAGE_BUCKET','OBJECT_STORAGE_ACCESS_KEY','OBJECT_STORAGE_SECRET_KEY',
            'OBJECT_STORAGE_ENDPOINT','OBJECT_STORAGE_REGION')}
        for k in self.old: os.environ.pop(k,None)
        s._client.cache_clear()

    def tearDown(self):
        for k,v in self.old.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v
        s._client.cache_clear()

    def test_database_fallback_is_default(self):
        self.assertFalse(s.configured())
        data,key,backend,checksum=s.persist_bytes('p','a','source','clip.mp4',b'abc','video/mp4')
        self.assertEqual(data,b'abc');self.assertIsNone(key);self.assertEqual(backend,'database')
        self.assertEqual(len(checksum),64)

    def test_key_is_private_and_sanitized(self):
        key=s.object_key('project','asset','render','../../weird name?.mp4')
        self.assertEqual(key,'projects/project/render/asset/weird_name_.mp4')
        self.assertNotIn('..',key)

    def test_s3_mode_round_trip_and_range(self):
        os.environ['OBJECT_STORAGE_BUCKET']='bucket'
        os.environ['OBJECT_STORAGE_ACCESS_KEY']='key'
        os.environ['OBJECT_STORAGE_SECRET_KEY']='secret'
        fake=FakeS3()
        with patch('storage_backend._client',return_value=fake):
            data,key,backend,_=s.persist_bytes('p','a','source','clip.mp4',b'0123456789','video/mp4')
            self.assertIsNone(data);self.assertEqual(backend,'s3');self.assertTrue(key.endswith('/clip.mp4'))
            self.assertEqual(s.get_bytes(key),b'0123456789')
            self.assertEqual(s.get_range(key,2,5),b'2345')
            s.delete(key);self.assertNotIn(key,fake.objects)


if __name__=='__main__':
    unittest.main()
