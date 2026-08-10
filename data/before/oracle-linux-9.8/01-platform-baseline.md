<!-- data/before/oracle-linux-9.8/01-platform-baseline.md -->
# Oracle Linux 9.8 플랫폼 기준

## 1. 적용 범위

이 기준은 x86_64 기반의 일반 애플리케이션 서버에 적용한다. aarch64는 Oracle Linux 9.8에서 지원되지만 UEK만 제공되므로 별도 하드웨어·애플리케이션 인증 절차를 사용한다.

## 2. 릴리스와 커널

Oracle Linux 9.8 Release Notes의 최초 게시 기준은 2026년 6월이다. x86_64 설치 미디어는 다음 커널을 제공한다.

| 구분 | 패키지·버전 | 사용 원칙 |
| --- | --- | --- |
| 기본 | `kernel-uek-6.12.0-203.76.7.3` | 신규 설치의 기본 부팅 커널 |
| 대체 | `kernel-5.14.0-687.5.3` | RHCK 인증이 필요한 워크로드에서 검토 |

기존 Oracle Linux 9 호스트를 update release로 갱신할 때 UEK R7에서 UEK R8로의 전환은 자동이라고 가정하지 않는다. 설치된 커널, 활성 저장소, 애플리케이션 공급자 인증을 확인한 뒤 변경한다. 커널 downgrade는 Oracle Support의 명시적 권고가 없는 한 수행하지 않는다.

## 3. 서버 기준 프로파일

| 항목 | 기준값 |
| --- | --- |
| 호스트명 | `ol98-app01.example.internal` |
| CPU 아키텍처 | `x86_64` |
| 시간대 | `Asia/Seoul` |
| 시간 동기화 | `chronyd` 활성 |
| 로케일 | `ko_KR.UTF-8` 또는 애플리케이션 인증 로케일 |
| SELinux | `Enforcing` |
| 방화벽 | `firewalld` 활성 |
| 암호화 정책 | `DEFAULT` |
| 원격 관리 | SSH key 기반, 직접 root 로그인 금지 |
| 기본 셸 | Bash |

## 4. 최초 점검 명령

다음 명령은 상태를 읽기만 하며 베이스라인 수집에 사용한다.

```bash
cat /etc/oracle-release
cat /etc/os-release
uname -r
uname -m
sudo grubby --default-kernel
sudo grubby --info=ALL
sudo dnf repolist
timedatectl status
systemctl is-enabled chronyd
systemctl is-active chronyd
getenforce
firewall-cmd --state
update-crypto-policies --show
```

## 5. 합격 조건

1. `/etc/oracle-release`가 Oracle Linux 9 계열을 나타낸다.
2. 실제 실행 커널이 승인된 UEK 또는 RHCK 계열이다.
3. 기본 부팅 커널과 현재 실행 커널의 차이가 설명된다.
4. BaseOS와 AppStream 핵심 저장소가 활성 상태다.
5. 시간 동기화, SELinux, firewalld가 기준 상태다.
6. 읽기 점검에서 자격정보, 실제 사내 IP, 고객 식별자를 수집하지 않는다.

## 6. 변경 관리

다음 변경은 재부팅과 애플리케이션 검증 가능성이 있으므로 사람 승인을 요구한다.

- UEK와 RHCK 전환
- 커널 major release 변경
- FIPS 모드 활성화
- 파일 시스템 축소 또는 재구성
- 기본 방화벽 zone과 대상 인터페이스 변경
- 시스템 암호화 정책 변경

## 7. 공식 근거

- [Oracle Linux 9.8 Release Notes](https://docs.oracle.com/en/operating-systems/oracle-linux/9/relnotes9.8/)
- [Available Architectures](https://docs.oracle.com/en/operating-systems/oracle-linux/9/relnotes9.8/ol9-AvailableArchitectures.html)
- [Shipped Kernels](https://docs.oracle.com/en/operating-systems/oracle-linux/9/relnotes9.8/ol9.8-ShippedKernels.html)
- [Oracle Linux 9 Documentation](https://docs.oracle.com/en/operating-systems/oracle-linux/9/)
