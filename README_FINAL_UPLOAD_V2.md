RetailRecon AI - Final Upload Ready V2

Additional hardening:
- Corrected global date parsing for actual source exports:
  8/1/2026 = 01-Aug-2026, 7/4/2026 = 04-Jul-2026.
- Supports D365 header Authcode / AuthorizationCode aliases.
- Preserves D365 Raw Auth Code and creates D365 Match Key.
- Exact Store 614 regression suite locks 11 supplied MADA/VISA/MASTER cases.
- Existing Tabby/Tamara/provider matching regressions retained.
