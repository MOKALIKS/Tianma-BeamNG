# 手动推送与发布

1. 在 GitHub Desktop 选择 **Tianma-BeamNG**，检查 Changes。
2. 填写提交摘要，例如 `Prepare Tianma BeamNG V1.0`，点击 **Commit to main**。
3. 点击 **Push origin** 或 **Publish branch**。
4. 打开仓库网页，进入 **Releases → Create a new release**。
5. 创建标签 `v1.0`，目标选择 `main`，标题填写 `Tianma BeamNG V1.0`。
6. 将 `releases/v1.0/RELEASE_NOTES.md` 的内容作为发布说明。
7. 上传最终构建的 `st_stctk_ac_port.zip` 和对应 `SHA256.txt`。
8. 检查附件与说明后点击 **Publish release**。

当前机器的最终附件位于 `F:\st_stctk\_beamng_conversion\output`。该路径是本次构建位置，其他机器应使用自己的 `<TrackRoot>/_beamng_conversion/output`。

地图 ZIP 超过 GitHub 普通 Git 单文件 100 MB 限制，已经被 `.gitignore` 排除。请上传为 Release 附件，不要强制加入 Git。若重新构建，请同步更新发布说明中的大小和哈希，以及 `releases/v1.0/SHA256.txt`。
