# Code signing

A signed `.msi` is the difference between non-pros breezing past install and
non-pros bouncing off Windows SmartScreen's red "Don't run" wall. Signing is
not optional for v1 release.

## Choosing a certificate


| Type                        | Cost / yr                         | SmartScreen                           | Notes                                                   |
| --------------------------- | --------------------------------- | ------------------------------------- | ------------------------------------------------------- |
| OV (Organization Validated) | ~$80 (SSL.com, Sectigo, GoGetSSL) | Reputation builds over downloads/time | Stored in software, easy to use in CI                   |
| EV (Extended Validation)    | ~$300                             | Instant clean SmartScreen             | Hardware token (USB / cloud HSM) required by CA/B Forum |


**Locked decision (DECISIONS.md):** OV cert for v1. Re-evaluate EV before
hitting 1k weekly active users; SmartScreen reputation typically takes a
few hundred installs to clear with an OV cert.

Recommended OV providers (no affiliation):

- [SSL.com — Code Signing OV](https://www.ssl.com/certificates/code-signing/)
- [Sectigo — Code Signing](https://sectigo.com/ssl-certificates-tls/code-signing)
- [GoGetSSL](https://www.gogetssl.com/code-signing/) (reseller, often cheaper)

## Local signing (developer machine)

1. Install the cert into the Windows Certificate Store (`certmgr.msc`,
  "Personal" store).
2. Find its SHA-1 thumbprint:
  ```powershell
   Get-ChildItem -Path Cert:\CurrentUser\My -CodeSigningCert
  ```
3. Set it in `tauri/tauri.conf.json` (or override at build time):
  ```json
   "windows": {
     "certificateThumbprint": "0123ABCDEF...",
     "digestAlgorithm": "sha256",
     "timestampUrl": "http://timestamp.sectigo.com"
   }
  ```
4. Build:
  ```powershell
   cd tauri; cargo tauri build
  ```
   The bundler will sign the `.exe` and the `.msi` automatically.

## CI signing (GitHub Actions)

We use the `[Dana-Prajea/code-sign-action](https://github.com/marketplace/actions/code-sign-action)`
pattern (or your CA's own action) so the cert never leaves the runner secrets.

```yaml
# .github/workflows/release.yml (excerpt)
- name: Build signed MSI
  env:
    WINDOWS_CERTIFICATE: ${{ secrets.WIN_PFX_BASE64 }}
    WINDOWS_CERTIFICATE_PASSWORD: ${{ secrets.WIN_PFX_PASSWORD }}
  run: |
    [IO.File]::WriteAllBytes("cert.pfx",
      [Convert]::FromBase64String("$env:WINDOWS_CERTIFICATE"))
    cargo tauri build --target x86_64-pc-windows-msvc -- `
      --windows-certificate-thumbprint $(certutil -dump cert.pfx |
        Select-String -Pattern "Cert Hash\(sha1\):" |
        ForEach-Object { ($_ -split ":")[1].Trim() })
```

For an EV cert held on a YubiKey or in Azure Key Vault, switch to
[AzureSignTool](https://github.com/vcsjones/AzureSignTool); see Microsoft's
trusted-signing service for a fully managed path.

## Verifying the signature

```powershell
Get-AuthenticodeSignature .\HermesDesk_0.1.0_x64_en-US.msi
# Expect: Status = Valid, SignerCertificate = your CN
signtool verify /pa /v .\HermesDesk_0.1.0_x64_en-US.msi
```

## Reputation warm-up

Even an OV-signed installer triggers SmartScreen at first because the
publisher reputation is empty. To accelerate it:

- Submit the binary to Microsoft Defender via the
[Microsoft Security Intelligence portal](https://www.microsoft.com/wdsi/filesubmission/)
- Distribute through GitHub Releases (`https://github.com` is a trusted
download source — better than a random CDN)
- Get early users to click "More info" -> "Run anyway" — each click
contributes to reputation. After roughly 200-500 installs the warning
goes away.
- Consider EV cert if your launch audience is non-technical from day one.

