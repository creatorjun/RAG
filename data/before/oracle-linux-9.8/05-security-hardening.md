<!-- data/before/oracle-linux-9.8/05-security-hardening.md -->
# Oracle Linux 9.8 보안 강화 기준

## 1. 보안 목표

플랫폼 기본 보안을 유지하면서 애플리케이션 호환성을 검증 가능한 방식으로 강화한다. 보안 기능을 장애 해결을 이유로 전역 비활성화하지 않는다.

## 2. 기준 상태

| 통제 | 기준 | 검증 |
| --- | --- | --- |
| SELinux | Enforcing | `getenforce` |
| 암호화 정책 | DEFAULT | `update-crypto-policies --show` |
| SSH | key 기반, 직접 root 로그인 금지 | `sshd -T` |
| firewalld | 활성, 최소 허용 | `firewall-cmd --list-all` |
| 패키지 서명 | DNF GPG 검사 활성 | `dnf config-manager --dump` |
| 시간 동기화 | chronyd 활성 | `chronyc tracking` |
| 감사 | auditd 활성 | `auditctl -s` |

## 3. SELinux

```bash
getenforce
sestatus
ls -Zd /opt/app /srv/app-data
sudo ausearch -m AVC,USER_AVC -ts recent
```

애플리케이션이 차단되면 SELinux를 permissive로 고정하지 않는다. 예상 경로와 포트를 확인하고 기존 타입을 우선 사용한다. 사용자 정의 파일 문맥이 필요한 경우 `semanage fcontext`로 영구 규칙을 만들고 `restorecon`으로 적용한다.

```bash
sudo semanage fcontext -a -t var_lib_t '/srv/app-data(/.*)?'
sudo restorecon -RFv /srv/app-data
```

타입 선택은 예시이며 실제 서비스 domain과 최소 권한을 검토한다. `audit2allow` 결과를 검토 없이 정책으로 적용하지 않는다.

## 4. 시스템 암호화 정책

Oracle Linux는 시스템 전역 암호화 정책을 제공한다. 현재 정책은 다음 명령으로 확인한다.

```bash
update-crypto-policies --show
```

기본 기준은 `DEFAULT`다. `LEGACY`는 호환성을 넓히지만 약한 알고리즘을 허용하므로 운영의 정상 해결책으로 사용하지 않는다. `FUTURE`, `DEFAULT:PQ`, FIPS 같은 강화 정책은 클라이언트·서버·인증서·애플리케이션 호환성 시험과 재부팅 계획을 거쳐 적용한다.

FIPS 모드는 암호화 정책 문자열만 바꾸는 작업으로 간주하지 않는다. 승인된 Oracle Linux FIPS 절차와 제품 인증 범위를 별도로 검토한다.

## 5. SSH

다음은 유효 설정을 읽는 점검이다.

```bash
sudo sshd -t
sudo sshd -T | grep -E 'permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|clientaliveinterval'
sudo systemctl is-active sshd
```

운영 기준:

- `PermitRootLogin no`
- 관리자는 개인 계정과 sudo를 사용
- 비밀번호 인증은 대체 접속 경로와 key 배포를 확인한 뒤 비활성화
- RSA를 사용할 경우 시스템 암호화 정책의 최소 key 길이 준수
- host key와 authorized key의 소유권·권한 검증
- 설정 reload 전에 `sshd -t` 통과

## 6. 패키지와 계정

```bash
sudo dnf updateinfo list security
sudo awk -F: '$3 == 0 {print $1}' /etc/passwd
sudo lastlog
sudo faillock --user test-operator
sudo systemctl --type=service --state=running
```

샘플 계정명은 실제 계정으로 대체한다. 사용하지 않는 서비스와 계정을 제거하기 전에 패키지 의존성, 자동화, 장애 복구 절차를 확인한다.

## 7. 변경 승인

다음 변경은 보안·애플리케이션 담당자의 공동 승인을 요구한다.

- SELinux 정책 모듈 추가
- 암호화 정책 변경
- FIPS 모드 전환
- SSH 인증 방식 변경
- 방화벽에 새 inbound 포트 추가
- 감사 규칙 또는 로그 보존 축소

## 8. 공식 근거

- [Configuring System Cryptographic Policies](https://docs.oracle.com/en/operating-systems/oracle-linux/9/security/security-ConfiguringSystemCryptograpicPolicies.html)
- [Understanding the Importance of Updates](https://docs.oracle.com/en/operating-systems/oracle-linux/9/security/security-AboutSystemSoftwareUpdates.html)
- [Administering SELinux](https://docs.oracle.com/en/operating-systems/oracle-linux/selinux/)
- [Oracle Linux 9 Security Documentation](https://docs.oracle.com/en/operating-systems/oracle-linux/9/)
