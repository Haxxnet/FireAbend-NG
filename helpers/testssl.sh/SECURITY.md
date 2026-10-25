# Security Policy

## Reporting a Vulnerability

This project takes security seriously  &mdash;this is meant literally &mdash;not like some companies claim after a breach or other security incident.

The attack surface of testssl.sh is quite small and thus there should not be any serious blunders. We followed recommended security practices, e.g. validate inputs and more.

However this project was made by humans and despite our dedication and diligence there could be still security bugs. If you find one and the impact is not low, please use [Responsible
Disclosure](https://en.wikipedia.org/wiki/Full_disclosure_(computer_security)#Coordinated_vulnerability_disclosure), see  [github docs](https://docs.github.com/en/enterprise-cloud@latest/code-security/how-tos/report-and-fix-vulnerabilities/report-privately) and report them *privately* . If you happen to have a PoC, it will be much appreciated but it is not mandatory. Using [Full Disclosure](https://en.wikipedia.org/wiki/Full_disclosure_(computer_security)#Full_disclosure) might be a problem everywhere where testssl.sh is being used -- just for for CLI users, maintainers of CI/CD or monitoring environment or for people using testssl.sh as a scanner on their website.

Also keep in mind that the maintainers here have a professional attitude but this project is volunteer work.

### How do I file a problem?

"Create new Issue" --> "Report a security vulnerability" . Then on the LHS you should see "Advisory" which you need to fill out. That stays private until we fixed your point or, if your point has no impact, disregard it.


## Supported Versions

As said in the Readme.md we only support n-1 versions , n being the branch/minor version:

| Branches | Supported          |
| -------- | ------------------ |
| 3.3dev   | :white_check_mark: |
| 3.2.x    | :white_check_mark: |
| 3.0.x    | :x:                |
| <=2.9.5  | :x:                |

For x (patch version) we expect your report to refer to the latest release. For the rolling release version (*dev) please refer to the latest and greatest @ github.

