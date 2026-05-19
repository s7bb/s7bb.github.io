# Decision: No login gate, no Impressum (2026-05-19)

**Status:** Decided — no implementation. Recorded so the question is not re-raised.

> Not legal advice. Author is not a lawyer. The legal reasoning below is the
> rationale for the decision, not a legal opinion. Re-verify with a lawyer if
> the site's purpose changes (ads, donations, sponsorship, commercial use).

## Question raised

Add a login screen in front of the site to circumvent the German
Impressumspflicht and avoid exposing the operator's identity. Can this be
done on GitHub Pages with HTTP Basic Auth?

## Decision

**Build nothing.** No login gate, no Basic Auth, no Impressum page, no code
change. The site already meets the actual goal.

## Threat model (agreed)

Hide operator identity **from casual Baierbrunn residents browsing the site**.
A public GitHub repository with real-name commit history is an accepted
residual — a curious neighbour who opens the repo is out of scope.

## Why a login gate was rejected

1. **Wrong layer.** Operator identity does not leak through the rendered site.
   It leaks through the public repo `s7bb/s7bb.github.io` and git commit
   authorship (`Martin Zehetmayer`). A frontend gate hides none of that.
2. **Verified clean frontend.** Scan of `site/src` + `index.html` (2026-05-19):
   zero occurrences of name, email, Impressum, Kontakt, GitHub link, or
   footer contact. Nav is only `Heute / Letzte 7 Tage / Statistik / Archiv /
   Methodik`. Nothing to hide there in the first place.
3. **Not cleanly possible on GitHub Pages.** Pages is static hosting with no
   server-side HTTP Basic Auth. A real gate requires an edge proxy
   (Cloudflare Access / Workers) in front of the site — new infrastructure
   that breaks the deploy boundary documented in `CLAUDE.md`. A client-side
   JavaScript "login" is trivially bypassed (view-source, direct fetch) and is
   security theatre.
4. **Data is already public anyway.** The site reads `latest.json` from the
   public repo `s7bb/s7bb-data`. Anyone can fetch it directly without the
   site. Gating the site hides no data. Making that repo private would break
   the Actions deploy and the "bot PAT has no access to this code repo"
   boundary.
5. **Legally moot.** Impressumspflicht (§ 5 DDG, formerly § 5 TMG) is
   triggered by the *geschäftsmäßige* (commercial-ish) nature of the
   telemedium, **not** by public accessibility. A login wall does not remove
   the duty where it exists, and does not create one where it does not.

## Impressum reasoning

A free, ad-free, donation-free hobby information page for residents has a
strong case for being non-*geschäftsmäßig* → **no Impressumspflicht**. Under
that reading, *not* publishing an Impressum is the correct move: adding one
would be the act that exposes the operator's name and address, for no legal
gain. This holds only while the site stays non-commercial.

## Residual risks (accepted)

- Public repo + real-name git history → operator discoverable by anyone who
  opens the GitHub repo. Accepted under the agreed threat model. No action.
- Legal classification depends on the site staying non-commercial. If ads,
  donations, sponsorship, or any commercial element is added, revisit this
  decision and obtain a legal opinion.

## Re-open triggers

Revisit only if: the site becomes commercial; the threat model strengthens
beyond "casual residents" (then the work is git-history + GitHub-account
scrubbing, not a frontend gate); or a legal notice is received.
