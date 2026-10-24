"""Deterministic authorization check for deletion intent."""

from __future__ import annotations

import re
import unicodedata


DELETION_PATTERNS = (
    r"\bdelet(?:e|ed|es|ing|ion|ions)\b",
    r"\beras(?:e|ed|ing|ure)\b",
    r"\bpurge\b",
    r"\bforget me\b",
    r"\bsuppression\b",
    r"\bsupprim(?:er|e|ée|ée|ée|ée|ée|ée|ée)\b",
    r"\beffac(?:er|e|ement)\b",
    r"\belimin(?:a|an|amos|ar|ado|ada|ación|ate|ation|are)\b",
    r"\bborr(?:ar|ado|ar)\b",
    r"\bexclu(?:ir|ir|sion)\b",
    r"\bapagar\b",
    r"\bcancell(?:are|ar|ation)\b",
    r"\bverwijder(?:en|ing)\b",
    r"\bl(?:ö|oe)sch(?:en|ung)\b",
    r"削除|消去|删除|刪除|삭제|حذف|मिटा|हटा",
    r"\bclose my account\b",
    r"\bclose this account\b",
    r"\bclose the account\b",
    r"\baccount (?:to be )?closed\b",
    r"\b(?:would like|want|wish|need) (?:it|them) (?:to be )?(?:closed|deleted|removed|erased)\b",
    r"\b(?:remove|erase|wipe) (?:my|this|the) (?:account|profile|personal data|personal information)\b",
    r"\b(?:remove|erase|wipe) (?:all )?(?:my )?(?:personal )?(?:data|information)\b",
    r"\b(?:remove|delete|erase|purge) (?:any )?(?:remaining )?(?:copies|records|results|profiles|accounts|data|details|traces|exports|attachments)\b",
    r"\b(?:remove|delete|erase|purge) (?:that|this|the) (?:search )?result\b",
    r"\b(?:remove|delete|erase|purge) records? (?:linked|associated|under|for)\b",
    r"\b(?:confirm|verify|check|inspect|audit) .{0,120}\b(?:account|profile|data|request)\b.{0,80}\b(?:gone|removed|deleted|erased)\b",
    r"\b(?:gone|removed|deleted|erased)\b.{0,80}\b(?:account|profile|data|request)\b.{0,80}\b(?:confirm|verify|check|inspect|audit)\b",
)

NEGATED_DELETION_PATTERNS = (
    r"\bdo not delete\b",
    r"\bdon['’]?t delete\b",
    r"\bnever delete\b",
    r"\bnot asking for (?:an? )?deletion\b",
    r"\bnot request(?:ing)? (?:an? )?deletion\b",
    r"\bwithdraw(?:ing)? (?:my )?(?:deletion|erasure) request\b",
    r"\bcancel (?:my )?(?:deletion|erasure) request\b",
    r"\bchanged my mind about (?:deleting|erasing)\b",
    r"\bkeep my account active\b",
)

NON_DELETION_ACTIONS = (
    r"\baccess\b",
    r"\bdownload\b",
    r"\bexport\b",
    r"\bcopy of\b",
    r"\bcorrect(?:ion)?\b",
    r"\bupdate\b",
    r"\breplace\b",
    r"\bchange\b",
    r"\bunsubscribe\b",
    r"\bopt[- ]?out\b",
    r"\bmarketing\b",
    r"アクセス|访问|訪問|修正|変更|訂正|نسخة",
)


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def authorizes_deletion(request_text: str) -> bool:
    """Return True only for affirmative deletion intent.

    This baseline intentionally does not consult reported workflow status.
    """
    text = _normalized(request_text)
    if any(re.search(pattern, text, flags=re.I) for pattern in NEGATED_DELETION_PATTERNS):
        return False
    if any(re.search(pattern, text, flags=re.I) for pattern in DELETION_PATTERNS):
        return True
    # Access, correction, portability, and marketing requests are not erasure.
    if any(re.search(pattern, text, flags=re.I) for pattern in NON_DELETION_ACTIONS):
        return False
    return False
