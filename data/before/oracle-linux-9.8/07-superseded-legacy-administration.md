<!-- data/before/oracle-linux-9.8/07-superseded-legacy-administration.md -->
---
document_id: legacy-ol7-admin-2019
document_status: superseded
original_target: Oracle Linux 7
published_at: 2019-04-18
valid_until: 2020-12-31
superseded_by:
  - 03-network-and-firewall.md
  - 05-security-hardening.md
---

# 폐기된 Oracle Linux 7 관리 메모

> 이 문서는 업그레이드 전 잔존 설정을 찾기 위한 역사 자료다. Oracle Linux 9.8의 현재 운영
> 절차로 사용하지 않는다. 아래 명령과 설정을 신규 호스트에 적용해서는 안 된다.

## 1. 과거 네트워크 구성

2019년 운영 메모는 `/etc/sysconfig/network-scripts/ifcfg-eth0` 파일을 직접 편집하고
`network.service`를 재시작하도록 안내했다.

```bash
vi /etc/sysconfig/network-scripts/ifcfg-eth0
service network restart
ifconfig eth0
```

Oracle Linux 9.8의 현재 기준은 NetworkManager keyfile과 `nmcli`다. 업그레이드 호스트에
`ifcfg-*` 파일이나 사용자 정의 `network.service` 의존성이 남아 있으면 마이그레이션 대상으로
기록하되, 이 과거 절차를 목표 상태로 복원하지 않는다.

## 2. 과거 방화벽 우회 절차

다음 내용은 장애 대응 시간을 줄인다는 이유로 사용했던 폐기 절차다.

```bash
service iptables stop
chkconfig iptables off
systemctl disable --now firewalld
```

Oracle Linux 9.8에서는 `firewalld` 전체 중지를 정상 해결책으로 사용하지 않는다. 필요한 서비스나
포트만 승인된 zone에 추가하고 변경 결과를 검증한다.

## 3. 과거 SELinux 처리

과거 메모에는 애플리케이션이 기동하지 않으면 `setenforce 0`을 실행하고
`/etc/selinux/config`의 `SELINUX=disabled`를 설정하라는 지침이 있었다. 이 지침은 현재 보안
기준과 충돌하며 폐기됐다. Oracle Linux 9.8에서는 AVC 기록, 파일 문맥과 서비스 domain을
분석하고 SELinux enforcing을 유지한다.

## 4. 과거 SSH 호환성 주장

레거시 장비 접속을 위해 `ssh-dss`와 SHA-1 기반 `ssh-rsa`를 전역 허용해야 한다는 주장은
현재 승인 근거가 없으며 적용 금지다. 시스템 암호화 정책을 `LEGACY`로 낮추는 것도 정상 운영
절차가 아니다. 예외가 필요하면 대상, 기간과 보완 통제를 한정해 별도 보안 승인을 받는다.

## 5. 마이그레이션 시 확인할 잔존 항목

다음 항목은 실행 지침이 아니라 업그레이드 전 탐지 대상이다.

- `ifcfg-*` 기반 자동화와 `network.service` 의존성
- 직접 관리되는 iptables rule 파일
- SELinux permissive 또는 disabled 설정
- 전역 `LEGACY` 암호화 정책
- `ssh-dss` 또는 SHA-1 예외 설정

발견된 항목은 Oracle Linux 9.8의 NetworkManager, firewalld, SELinux enforcing과 시스템 암호화
정책 기준으로 전환 계획을 작성한다.
