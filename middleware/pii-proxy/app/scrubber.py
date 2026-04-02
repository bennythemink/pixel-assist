import logging
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import NlpEngineProvider
from app.session_store import SessionStore
from app.config import SCRUB_SCORE_THRESHOLD, SESSION_TTL_HOURS

logger = logging.getLogger("pii-proxy")

ENTITY_LABEL_MAP = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "AU_PHONE": "PHONE",
    "AU_ADDRESS": "ADDRESS",
    "AU_DOB": "DOB",
    "AU_MEDICARE": "MEDICARE",
    "AU_ABN": "ABN",
    "AU_ACN": "ACN",
}

ENTITIES_TO_DETECT = list(ENTITY_LABEL_MAP.keys())

session_store = SessionStore(ttl_hours=SESSION_TTL_HOURS)


def _build_au_phone_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="AU_PHONE",
        patterns=[
            Pattern("au_mobile_spaced", r"\b04\d{2}\s\d{3}\s\d{3}\b", 0.7),
            Pattern("au_mobile_compact", r"\b04\d{8}\b", 0.7),
            Pattern("au_mobile_intl", r"\+61\s?4\d{2}\s?\d{3}\s?\d{3}\b", 0.9),
            Pattern("au_landline_parens", r"\(0[2-9]\)\s?\d{4}\s?\d{4}", 0.7),
            Pattern("au_landline", r"\b0[2-9]\s?\d{4}\s?\d{4}\b", 0.6),
            Pattern("au_intl_landline", r"\+61\s?[2-9]\s?\d{4}\s?\d{4}\b", 0.9),
        ],
        context=["phone", "mobile", "cell", "contact", "call", "ring", "number", "tel"],
        supported_language="en",
    )


def _build_abn_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="AU_ABN",
        patterns=[
            Pattern("abn", r"\b\d{2}\s?\d{3}\s?\d{3}\s?\d{3}\b", 0.3),
        ],
        context=["ABN", "abn", "business number", "australian business number"],
        supported_language="en",
    )


def _build_acn_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="AU_ACN",
        patterns=[
            Pattern("acn", r"\b\d{3}\s?\d{3}\s?\d{3}\b", 0.2),
        ],
        context=["ACN", "acn", "company number", "australian company number"],
        supported_language="en",
    )


def _build_medicare_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="AU_MEDICARE",
        patterns=[
            Pattern("medicare", r"\b[2-6]\d{3}\s?\d{5}\s?\d{1,2}\b", 0.3),
        ],
        context=["Medicare", "medicare", "Medicare number", "card number", "medicare card"],
        supported_language="en",
    )


def _build_address_recognizer() -> PatternRecognizer:
    st = (
        r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|"
        r"Lane|Ln|Crescent|Cres|Boulevard|Blvd|Way|Parade|Pde|"
        r"Terrace|Tce|Highway|Hwy|Close|Cl|Circuit|Cct|Grove|Gr|"
        r"Square|Sq|Walk|Rise|View)\b"
    )
    states = r"(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT)"
    suffix = rf"(?:\s*,?\s+[A-Za-z]+(?:\s+[A-Za-z]+){{0,2}}\s+{states}\s+\d{{4}})?"

    return PatternRecognizer(
        supported_entity="AU_ADDRESS",
        patterns=[
            Pattern(
                "au_address_unit",
                rf"(?i)(?:(?:Unit|Flat|Apt|Suite|Level)\s+\d+[A-Za-z]?\s*,?\s+)\d+[A-Za-z]?\s+[A-Za-z']+(?:\s+[A-Za-z']+){{0,2}}\s+{st}{suffix}",
                0.85,
            ),
            Pattern(
                "au_address_slash",
                rf"(?i)\d+[A-Za-z]?\s*/\s*\d+[A-Za-z]?\s+[A-Za-z']+(?:\s+[A-Za-z']+){{0,2}}\s+{st}{suffix}",
                0.85,
            ),
            Pattern(
                "au_address_basic",
                rf"(?i)\b\d+[A-Za-z]?\s+[A-Za-z']+(?:\s+[A-Za-z']+){{0,2}}\s+{st}{suffix}",
                0.7,
            ),
        ],
        context=["address", "live", "living", "located", "location", "reside", "property", "renovation"],
        supported_language="en",
    )


def _build_dob_recognizer() -> PatternRecognizer:
    months = (
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    )

    return PatternRecognizer(
        supported_entity="AU_DOB",
        patterns=[
            Pattern("dob_numeric", r"(?i)\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b", 0.1),
            Pattern("dob_text_dmy", rf"(?i)\b\d{{1,2}}\s+{months}\s+\d{{2,4}}\b", 0.1),
            Pattern("dob_text_mdy", rf"(?i)\b{months}\s+\d{{1,2}}(?:\s*,?\s+\d{{2,4}})?\b", 0.1),
        ],
        context=["born", "dob", "date of birth", "birthday", "d.o.b", "birth date", "birthdate"],
        supported_language="en",
    )


def _build_analyzer() -> AnalyzerEngine:
    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
    }
    provider = NlpEngineProvider(nlp_configuration=configuration)
    nlp_engine = provider.create_engine()

    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["en"],
    )

    analyzer.registry.add_recognizer(_build_au_phone_recognizer())
    analyzer.registry.add_recognizer(_build_abn_recognizer())
    analyzer.registry.add_recognizer(_build_acn_recognizer())
    analyzer.registry.add_recognizer(_build_medicare_recognizer())
    analyzer.registry.add_recognizer(_build_address_recognizer())
    analyzer.registry.add_recognizer(_build_dob_recognizer())

    return analyzer


_analyzer = _build_analyzer()


def _resolve_overlaps(results):
    if not results:
        return results
    sorted_results = sorted(results, key=lambda r: (-(r.end - r.start), -r.score))
    resolved = []
    for result in sorted_results:
        overlaps = False
        for accepted in resolved:
            if result.start < accepted.end and result.end > accepted.start:
                overlaps = True
                break
        if not overlaps:
            resolved.append(result)
    return resolved


def scrub(message: str, session_id: str) -> str:
    try:
        results = _analyzer.analyze(
            text=message,
            entities=ENTITIES_TO_DETECT,
            language="en",
            score_threshold=SCRUB_SCORE_THRESHOLD,
        )
    except Exception:
        logger.exception("Presidio analysis failed — returning original message")
        return message

    if not results:
        return message

    results = _resolve_overlaps(results)

    entity_counts = {}
    for r in results:
        entity_counts[r.entity_type] = entity_counts.get(r.entity_type, 0) + 1
    logger.info("PII detected: %s", entity_counts)

    results.sort(key=lambda r: r.start, reverse=True)

    scrubbed = message
    for result in results:
        entity_text = message[result.start:result.end]
        label = ENTITY_LABEL_MAP.get(result.entity_type, result.entity_type)
        placeholder = session_store.get_or_create_placeholder(session_id, label, entity_text)
        scrubbed = scrubbed[:result.start] + placeholder + scrubbed[result.end:]

    logger.debug("Scrubbed message: %s", scrubbed)
    return scrubbed
