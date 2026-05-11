# Architecture

LLM Key Router separates credential health, provider/model availability, local daily caps, model fallback routing, and output quality evaluation.

A model/provider 429 does not globally poison a key. Auth failures and quota/payment failures can block a credential.
