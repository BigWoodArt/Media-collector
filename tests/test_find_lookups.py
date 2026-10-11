import io, json, unittest
from unittest import mock
from sources.kemono_source import CoomerSource
from sources.erome_source import EromeSource
from sources.fapello_source import FapelloSource
from sources.freesound_source import FreesoundSource
from sources.hentaifoundry_source import HentaiFoundrySource


class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake(routes):
    def op(req, timeout=None):
        url = getattr(req, "full_url", req)
        for k, v in routes.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return _R(v if isinstance(v, bytes) else json.dumps(v).encode())
        raise OSError("no route " + url)
    return op


class FindLookups(unittest.TestCase):
    def test_coomer_post_search(self):
        posts = {"posts": [{"service": "fansly", "user": "42", "title": "x"}] * 3 + [{"service": "onlyfans", "user": "7"}]}
        with mock.patch("urllib.request.urlopen", fake({"/api/v1/creators": [], "/api/v1/posts": posts})):
            r = CoomerSource.suggest("sunset beach")
        self.assertEqual(r[0]["value"], "fansly/user/42")
        self.assertIn("3 posts", r[0]["label"])

    def test_erome_count(self):
        html = "".join(f'<a href="https://www.erome.com/a/A{i}"></a>' for i in range(5)) + '<a href="/search?q=x&page=2">'
        with mock.patch("urllib.request.urlopen", fake({"erome.com/search": html.encode()})):
            r = EromeSource.suggest("cat")
        self.assertEqual(r[0]["count"], 5)
        self.assertIn("5+ albums", r[0]["label"])

    def test_fapello_count_and_missing(self):
        page = "".join(f'<a href="https://fapello.com/mia/{i}/">' for i in range(1, 4))
        with mock.patch("urllib.request.urlopen", fake({"/ajax/model/mia/": page.encode()})):
            r = FapelloSource.suggest("mia")
        self.assertEqual(r[0]["count"], 3)
        import urllib.error
        err = urllib.error.HTTPError("u", 404, "nf", {}, None)
        with mock.patch("urllib.request.urlopen", fake({"/ajax/model/": err})):
            self.assertEqual(FapelloSource.suggest("nobody"), [])

    def test_freesound_and_hf_without_credentials(self):
        with mock.patch("core.settings.load", return_value={"credentials": {}}):
            self.assertIn("API key", FreesoundSource.suggest("rain")[0]["label"])
            self.assertIn("connect browser", HentaiFoundrySource.suggest("cat")[0]["label"])

    def test_freesound_count(self):
        with mock.patch("core.settings.load", return_value={"credentials": {"freesound": {"api_key": "k"}}}), \
             mock.patch("urllib.request.urlopen", fake({"freesound.org/apiv2": {"count": 123}})):
            self.assertEqual(FreesoundSource.suggest("rain")[0]["count"], 123)


if __name__ == "__main__":
    unittest.main()
