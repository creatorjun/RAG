<!-- data/before/oracle-linux-9.8/02-package-and-kernel-operations.md -->
# Oracle Linux 9.8 패키지와 커널 운영

## 1. 목적

승인된 Oracle Linux 저장소를 사용해 패키지와 보안 errata를 일관되게 관리한다. RPM 파일을 직접 설치·삭제하는 절차보다 DNF 트랜잭션을 우선한다.

## 2. 핵심 저장소

| 저장소 | 목적 | 운영 기준 |
| --- | --- | --- |
| `ol9_baseos_latest` | 핵심 운영체제와 누적 errata | 필수 |
| `ol9_appstream` | 애플리케이션 스트림 패키지 | 필수 |
| `ol9_UEKR8` | UEK 8 커널 | UEK 기준 호스트에서 활성 |
| 개발자·EPEL 계열 | 개발·추가 패키지 | 운영 기본 비활성, 예외 승인 |

저장소 상태는 호스트 역할과 아키텍처에 따라 다를 수 있다. 정확한 저장소 목록을 문서에 고정하지 않고 실행 시점의 `dnf repolist --enabled` 결과를 변경 기록에 첨부한다.

## 3. 사전 점검

```bash
sudo dnf repolist --enabled
sudo dnf check
sudo dnf makecache
sudo dnf updateinfo list security
sudo dnf updateinfo summary
df -h / /boot /var
findmnt /boot
```

다음 조건이면 자동 패치를 중지한다.

- 저장소 서명 검증 오류
- `/boot` 또는 `/var` 여유 공간 부족
- 현재 커널 모듈과 새 커널의 공급자 인증 미확인
- 중요 서비스의 백업 또는 복구 지점 없음
- 패키지 의존성 충돌

## 4. 표준 패치 절차

1. 변경 티켓과 유지보수 창을 확인한다.
2. 현재 패키지, 커널, 저장소 상태를 수집한다.
3. 애플리케이션 데이터와 시스템 설정 백업을 검증한다.
4. 보안 errata와 전체 업데이트 후보를 검토한다.
5. 승인된 범위로 DNF 트랜잭션을 수행한다.
6. 재부팅 필요 여부와 새 기본 커널을 확인한다.
7. 재부팅 후 플랫폼·애플리케이션 smoke test를 수행한다.
8. 패키지 변경 목록과 검증 결과를 실행 기록에 남긴다.

```bash
sudo dnf upgrade --refresh
sudo dnf needs-restarting -r
sudo grubby --default-kernel
```

`dnf upgrade`와 `dnf update`는 전체 설치 패키지를 갱신하는 동의어로 사용할 수 있다. 자동화에서는 팀 표준인 `dnf upgrade`로 통일한다.

## 5. 보안 업데이트 우선 적용

보안 취약점 대응은 다음 조회 결과를 기준으로 승인한다.

```bash
sudo dnf updateinfo list security
sudo dnf updateinfo info --security
sudo dnf upgrade --security
```

특정 CVE 또는 errata만 적용할 때는 전체 의존성과 누적 패키지 특성을 검토한다. 오래된 패키지 release를 유지하면서 개별 수정만 임의로 분리한다고 가정하지 않는다.

## 6. 커널 확인

```bash
uname -r
rpm -q kernel-uek
rpm -q kernel
sudo grubby --default-kernel
sudo grubby --info=ALL
```

UEK와 RHCK를 동시에 설치할 수 있지만 운영 기본 커널은 하나만 지정한다. 커널 변경 전에 다음을 확인한다.

- 애플리케이션과 보안 에이전트 인증
- 외부 커널 모듈 재컴파일 필요성
- Secure Boot 서명 상태
- Kdump capture kernel과 예약 메모리
- 롤백 가능한 이전 커널 항목

## 7. 실패와 롤백

DNF 트랜잭션 실패 시 반복 실행 전에 원인을 분류한다. 저장소 일시 장애는 재시도할 수 있지만 GPG, 의존성, 디스크, 정책 위반은 사람 검토가 필요하다. 부팅 실패 시 GRUB에서 검증된 이전 커널로 부팅하고, 새 커널 제거 여부는 장애 근거와 공급자 지침을 검토한 뒤 결정한다.

## 8. 공식 근거

- [Installing Software on Oracle Linux](https://docs.oracle.com/en/operating-systems/oracle-linux/software-management/sfw-mgmt-InstallSoftwareonEnterpriseLinux.html)
- [Available Yum Repositories](https://docs.oracle.com/en/operating-systems/oracle-linux/software-management/sfw-mgmt-AvailableYumRepositories.html)
- [Understanding the Importance of Updates](https://docs.oracle.com/en/operating-systems/oracle-linux/9/security/security-AboutSystemSoftwareUpdates.html)
- [Oracle Linux 9.8 Shipped Kernels](https://docs.oracle.com/en/operating-systems/oracle-linux/9/relnotes9.8/ol9.8-ShippedKernels.html)
