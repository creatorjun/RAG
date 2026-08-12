<!-- data/before/oracle-linux-9.8/README.md -->
# Oracle Linux 9.8 사내 운영 문서 샘플

## 1. 목적

이 데이터셋은 대용량 문서 RAG 파이프라인을 빠르게 검증하기 위한 합성 기술 문서다. 실제 사내 호스트, 계정, 고객, 주소, 자격정보는 포함하지 않는다. 명령과 구성 예시는 격리된 테스트 환경에서 검증한 뒤 운영에 적용한다.

## 2. 기준 상태

- 제품: Oracle Linux 9.8
- 확인 기준일: 2026-08-10
- 대상: x86_64 서버
- 신규 설치 기본 커널: UEK 8 Update 2 `6.12.0-203.76.7.3`
- 대체 커널: RHCK `5.14.0-687.5.3`
- 기본 파일 시스템 설계: XFS와 LVM
- 네트워크 관리: NetworkManager와 `nmcli`
- 호스트 방화벽: `firewalld`
- 보안 기준: SELinux enforcing, 시스템 암호화 정책 DEFAULT

Oracle Linux 9의 update release는 독립적으로 고정할 버전이 아니라 최신 지원 패키지의 롤링 스냅샷이다. 따라서 문서 제목과 설치 미디어 기준은 9.8을 사용하더라도 운영 호스트는 승인된 저장소에서 최신 errata를 적용하며, 정확한 설치 패키지 버전은 실행 시점에 다시 수집한다.

## 3. 문서 구성

| 문서 | 내용 | 주요 시험 |
| --- | --- | --- |
| [플랫폼 기준](01-platform-baseline.md) | 릴리스, 커널, 시간, 기본 점검 | 버전 주장 추출, 표 파싱 |
| [패키지·커널 운영](02-package-and-kernel-operations.md) | 저장소, DNF, 패치, 커널 확인 | 명령 블록, 최신성 검증 |
| [네트워크·방화벽](03-network-and-firewall.md) | NetworkManager, keyfile, firewalld | 설정 주장, 보안 질의 필터 |
| [스토리지·백업·Kdump](04-storage-backup-and-kdump.md) | XFS, LVM, 백업, 크래시 덤프 | 구조 청킹, 절차 합성 |
| [보안 강화](05-security-hardening.md) | SELinux, 암호화 정책, SSH, 감사 | 보안 주장과 승인 게이트 |
| [서비스 운영 Runbook](06-service-operations-runbook.md) | 배포, 상태 점검, 장애 대응 | 중복 탐지, Map-Reduce 합성 |
| [폐기된 레거시 관리 메모](07-superseded-legacy-administration.md) | Oracle Linux 7의 폐기 절차와 마이그레이션 잔존 항목 | 오래된 지식의 현재 지침 오인 방지 |
| [혼합 공지·런타임 메모](08-mixed-communications-and-runtime-notes.md) | 비기술 공지, 승인 기술값, 기각 주장, 시험용 민감 문자열 | 기술 정보 회수와 노이즈·비밀 제외 |

품질 정답은 입력 데이터에 포함하지 않고
`tests/fixtures/quality/oracle-linux-9.8-noise-oracle.yaml`에서 관리한다. 최종 문서는 혼합 문서의
승인된 systemd 설정을 보존하면서 비기술 문구와 시험용 비밀값을 제외해야 한다. 폐기된 절차를
남길 필요가 있다면 현재 실행 절차가 아니라 레거시·금지·마이그레이션 문맥으로만 표시해야 한다.

생성된 문서는 프로젝트 루트에서 다음 명령으로 자동 채점한다.

```bash
venv/bin/python scripts/evaluate_noise_quality.py \
  data/after/integrated-technical-guide.md
```

종료 코드 `0`은 모든 기준 통과, `1`은 실패를 뜻한다. JSON 결과에는 현재 기술 사실 회수율,
비기술·민감 문자열 누출 건수와 한정되지 않은 폐기·기각 주장 목록이 포함된다.

## 4. 테스트용 가상 자원

모든 예시 식별자는 문서용 예약값이다.

| 항목 | 값 |
| --- | --- |
| 호스트명 | `ol98-app01.example.internal` |
| 애플리케이션 주소 | `192.0.2.10/24` |
| 게이트웨이 | `192.0.2.1` |
| DNS | `192.0.2.53` |
| 운영자 접근 대역 | `198.51.100.0/24` |
| 서비스 포트 | `8443/tcp` |

`192.0.2.0/24`와 `198.51.100.0/24`는 문서 예시에 사용하는 주소이며 실제 사내 네트워크를 의미하지 않는다.

## 5. 검토가 필요한 주장

다음 항목은 웹 검증과 사람 승인을 거쳐야 한다.

1. 설치 미디어에 포함된 정확한 커널 패키지와 운영 저장소의 현재 최신 커널이 같은지 여부
2. 애플리케이션 공급자가 UEK 8U2 또는 RHCK를 인증했는지 여부
3. 조직 보안 기준이 DEFAULT 암호화 정책보다 강한 별도 정책을 요구하는지 여부
4. 백업 RPO·RTO와 Kdump 보존 용량이 실제 서비스 등급에 맞는지 여부
5. 외부 공개 문서의 변경 사항을 사내 운영 기준에 적용할지 여부

## 6. 공식 근거

- [Oracle Linux 9 문서 허브](https://docs.oracle.com/en/operating-systems/oracle-linux/9/)
- [Oracle Linux 9.8 Release Notes](https://docs.oracle.com/en/operating-systems/oracle-linux/9/relnotes9.8/)
- [Oracle Linux 9.8 Shipped Kernels](https://docs.oracle.com/en/operating-systems/oracle-linux/9/relnotes9.8/ol9.8-ShippedKernels.html)
