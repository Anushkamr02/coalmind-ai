"""Topic/word-cloud module (blueprint 6.9). Two tiers:
  Tier 1 (preferred): BERTopic + sentence-transformers if installed
  Tier 2 (fallback):  TF-IDF + NMF (always available with sklearn)"""
import re
from .config import DOMAIN_STOP
from . import db

EXTRA_STOP = {"per","india","coal","mine","mines","colliery","seam","tonnes","tonne","limited","ltd",
              "subsidiary","table","chapter","directory","source","note","million","lakh","thousand",
              "sl","no","total","year","years","fy","page","data","figure","value","unit","amount",
              "production","report","company","ministry","government","india","statement"}
ALL_STOP = DOMAIN_STOP | EXTRA_STOP


def get_corpus():
    con = db.connect()
    rows = con.execute("SELECT text FROM chunks WHERE LENGTH(text) > 60 LIMIT 2000").fetchall()
    con.close()
    return [r[0] for r in rows]


def clean_tok(text):
    t = re.sub(r"[^a-z\s]", " ", text.lower())
    return " ".join(w for w in t.split() if len(w) > 3 and w not in ALL_STOP)


def tfidf_topics(docs, n_topics=8, n_words=10):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import NMF
    import numpy as np
    cleaned = [clean_tok(d) for d in docs]
    valid = [c for c in cleaned if c.strip()]
    if len(valid) < 3:
        return []
    vec = TfidfVectorizer(max_df=0.9, min_df=1, ngram_range=(1,2), max_features=1000)
    X = vec.fit_transform(valid)
    n = min(n_topics, X.shape[0]-1, X.shape[1]-1)
    if n < 2:
        return []
    model = NMF(n_components=n, random_state=42, max_iter=400)
    model.fit(X)
    feats = vec.get_feature_names_out()
    topics = []
    for i, comp in enumerate(model.components_):
        top = [feats[j] for j in comp.argsort()[:-n_words-1:-1] if comp[j] > 0]
        score = float(np.sum(comp[comp > 0]))
        topics.append(dict(topic=i, label=", ".join(top[:5]), words=top, score=score))
    return sorted(topics, key=lambda x: -x["score"])


def wordcloud_freqs(docs, n=60):
    from collections import Counter
    counter = Counter()
    for d in docs:
        counter.update(clean_tok(d).split())
    return dict(counter.most_common(n))


def get_topics():
    docs = get_corpus()
    if not docs:
        return {"topics": [], "freqs": {}, "source": "no data", "n_docs": 0}
    try:
        from bertopic import BERTopic
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.feature_extraction._stop_words import ENGLISH_STOP_WORDS
        vmod = CountVectorizer(stop_words=list(ENGLISH_STOP_WORDS | ALL_STOP), ngram_range=(1,2))
        m = BERTopic(vectorizer_model=vmod, min_topic_size=max(2, len(docs)//10), nr_topics="auto")
        m.fit_transform(docs)
        topics = [dict(topic=tid, label=", ".join(w for w, _ in ws[:5]),
                       words=[w for w, _ in ws], score=sum(sc for _, sc in ws))
                  for tid, ws in [(t, m.get_topic(t)) for t in m.get_topics() if t != -1] if ws]
        source = "BERTopic"
    except ImportError:
        topics = tfidf_topics(docs)
        source = "TF-IDF + NMF"
    freqs = wordcloud_freqs(docs)
    return {"topics": topics, "freqs": freqs, "source": source, "n_docs": len(docs)}
