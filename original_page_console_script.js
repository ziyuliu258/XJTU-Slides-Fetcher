(async () => {
    console.log("%c🚀 XJTU LMS 资源自动嗅探工具启动...", "color: #007bff; font-weight: bold;");

    // 1. 自动从 URL 解析 ID
    const match = window.location.href.match(/course\/(\d+)\/.*#\/(\d+)/);
    if (!match) {
        console.error("❌ 无法解析课程 ID，请确保你在学习活动详情页。");
        return;
    }
    const [_, courseId, activityId] = match;

    try {
        // 2. 获取活动的原始元数据
        const res = await fetch(`/api/activities/${activityId}`);
        const json = await res.json();
        
        // 3. 提取文件列表
        const uploads = json.uploads || (json.data && json.data.uploads) || [];
        if (uploads.length === 0) {
            console.warn("⚠️ 该活动未检测到上传的文件。");
            return;
        }

        console.log(`%c📦 发现 ${uploads.length} 个资源，正在破解下载链接...`, "color: #17a2b8;");

        for (let file of uploads) {
            // 尝试通过预览接口获取 CDN 真实地址
            const previewPath = `/api/uploads/${file.id}/preview`;
            const check = await fetch(previewPath);
            
            if (check.ok) {
                const data = await check.json();
                const finalLink = data.url || data.link || data.redirect_url;
                
                if (finalLink) {
                    console.log(`%c✅ 抓取成功: ${file.name}`, "color: #28a745; font-weight: bold;");
                    console.log("🔗 直链: ", finalLink);
                    window.open(finalLink, '_blank');
                } else {
                    // 备选方案：直接尝试构造 API 下载
                    console.log(`%c尝试备选下载: ${file.name}`, "color: #6c757d;");
                    window.open(`/api/attachments/${file.reference_id}/download`, '_blank');
                }
            }
        }
    } catch (e) {
        console.error("💥 脚本运行出错:", e);
    }
})();