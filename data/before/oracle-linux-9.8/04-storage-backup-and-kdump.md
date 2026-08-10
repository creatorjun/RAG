<!-- data/before/oracle-linux-9.8/04-storage-backup-and-kdump.md -->
# Oracle Linux 9.8 스토리지, 백업, Kdump

## 1. 기본 설계

Oracle Linux 9의 기본 설치 레이아웃은 `/boot/EFI`의 VFAT를 제외한 볼륨에 XFS를 사용하고 `/`, `/home`, swap에 LVM을 사용한다. 실제 서버의 용량은 서비스 데이터, 로그 증가율, 백업 창, crash dump 크기를 기준으로 산정한다.

| 마운트 | 파일 시스템 | 예시 크기 | 용도 |
| --- | --- | ---: | --- |
| `/boot/efi` | VFAT | 600MiB | UEFI 시스템 파티션 |
| `/boot` | XFS | 1GiB 이상 | 커널과 initramfs |
| `/` | XFS on LVM | 40GiB | 운영체제 |
| `/var` | XFS on LVM | 40GiB | 로그와 패키지 캐시 |
| `/opt/app` | XFS on LVM | 20GiB | 애플리케이션 바이너리 |
| `/srv/app-data` | XFS on LVM | 업무 산정 | 애플리케이션 데이터 |

표의 크기는 테스트 예시다. `/boot`에는 여러 커널과 Kdump 이미지가 들어가므로 패치 전 여유 공간을 검사한다.

## 2. 상태 점검

```bash
lsblk -f
findmnt --verify
df -hT
df -ih
sudo pvs
sudo vgs
sudo lvs -a -o +devices
sudo xfs_info /srv/app-data
sudo du -x -h --max-depth=1 /var
```

## 3. LVM 확장 절차

XFS는 확장을 지원하지만 축소 절차로 사용하지 않는다. 다음 예시는 기존 volume group에 여유 extent가 있고 `/srv/app-data`가 XFS일 때만 적용한다.

```bash
sudo vgs
sudo lvs
sudo lvextend -L +10G /dev/mapper/ol-appdata
sudo xfs_growfs /srv/app-data
df -hT /srv/app-data
```

변경 전 device mapper 경로, 백업, VG 여유, 파일 시스템 유형을 확인한다. 명령 인자를 문서 예시에서 그대로 복사하지 않는다.

## 4. 백업 기준

| 대상 | 방식 | 예시 RPO | 예시 보존 |
| --- | --- | ---: | ---: |
| 애플리케이션 데이터 | 애플리케이션 일관 스냅샷과 원격 백업 | 1시간 | 30일 |
| 구성 파일 | 패키지·배포 매니페스트와 암호화 백업 | 24시간 | 90일 |
| 데이터베이스 | 제품 고유 온라인 백업 | 업무 정의 | 업무 정의 |
| 시스템 목록 | 패키지, mount, service, firewall 상태 | 변경 시 | 1년 |
| Kdump | `/var/crash` 별도 용량·보존 | 사고 시 | 사고 종료 후 정책 |

백업 성공 로그만으로 복구 가능성을 확정하지 않는다. 정기적으로 격리 호스트에 복원하고 파일 해시, 서비스 기동, 데이터 일관성을 검증한다.

## 5. Kdump

Kdump는 커널 장애 시 capture kernel로 전환해 메모리 내용을 `vmcore`로 저장한다. 일반 Oracle Linux 시스템의 기본 경로는 `/var/crash`다.

```bash
sudo dnf install kexec-tools
sudo systemctl enable --now kdump.service
systemctl is-enabled kdump.service
systemctl is-active kdump.service
kdumpctl status
grep -E 'crashkernel|path|core_collector' /etc/kdump.conf /proc/cmdline
df -h /var/crash
```

Kdump 설정과 `crashkernel` 예약 변경은 재부팅이 필요할 수 있다. 메모리 예약, dump 크기, 암호화, 외부 저장 위치, 민감정보 취급을 함께 검토한다. 운영 호스트에서 강제 crash 시험은 별도 승인과 격리된 유지보수 창 없이 수행하지 않는다.

## 6. 장애 대응

1. 파일 시스템 read-only 전환, I/O 오류, VG 누락 여부를 식별한다.
2. 쓰기 작업과 자동 재시도를 중지한다.
3. console, journal, storage controller 상태를 보존한다.
4. 파일 시스템 repair는 복제본 또는 공급자 지침을 우선한다.
5. 백업 복구가 필요한 경우 원본 장치를 덮어쓰기 전에 증거 이미지를 보존한다.
6. 복구 후 mount, 애플리케이션 데이터, 백업 체인을 재검증한다.

## 7. 공식 근거

- [Default Disk Partition Layout](https://docs.oracle.com/en/operating-systems/oracle-linux/9/install/install-DefaultDiskPartitionLayout.html)
- [Installing Kdump](https://docs.oracle.com/en/operating-systems/oracle-linux/9/boot/monitoring-InstallingKdump.html)
- [Configuring Kdump](https://docs.oracle.com/en/operating-systems/oracle-linux/9/boot/monitoring-ConfiguringKdump.html)
- [About Backup and Disaster Recovery](https://docs.oracle.com/en/operating-systems/oracle-linux/backup/backup-about-backup.html)
