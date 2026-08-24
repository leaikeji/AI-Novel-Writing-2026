export function compressCover(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith("image/")) {
      reject(new Error("请选择图片文件"));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error("图片格式无法识别"));
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 540;
        canvas.height = 720;
        const context = canvas.getContext("2d");
        if (!context) {
          reject(new Error("当前浏览器无法处理封面"));
          return;
        }
        const sourceRatio = image.width / image.height;
        const targetRatio = 3 / 4;
        let sx = 0;
        let sy = 0;
        let sw = image.width;
        let sh = image.height;
        if (sourceRatio > targetRatio) {
          sw = image.height * targetRatio;
          sx = (image.width - sw) / 2;
        } else {
          sh = image.width / targetRatio;
          sy = (image.height - sh) / 2;
        }
        context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
        let value = canvas.toDataURL("image/jpeg", 0.76);
        if (value.length > 170_000) value = canvas.toDataURL("image/jpeg", 0.52);
        if (value.length > 190_000) {
          reject(new Error("封面压缩后仍然过大，请换一张图片"));
          return;
        }
        resolve(value);
      };
      image.src = String(reader.result || "");
    };
    reader.readAsDataURL(file);
  });
}

export function generateSystemCover(title: string, author: string, audience: string): string {
  const canvas = document.createElement("canvas");
  canvas.width = 540;
  canvas.height = 720;
  const context = canvas.getContext("2d");
  if (!context) return "";

  const gradient = context.createLinearGradient(0, 0, 0, canvas.height);
  if (audience === "female") {
    gradient.addColorStop(0, "#59d7d1");
    gradient.addColorStop(0.52, "#7fcdd8");
    gradient.addColorStop(1, "#b994dc");
  } else {
    gradient.addColorStop(0, "#2f92ad");
    gradient.addColorStop(0.55, "#356b96");
    gradient.addColorStop(1, "#564b88");
  }
  context.fillStyle = gradient;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.strokeStyle = "rgba(255,255,255,.2)";
  context.lineWidth = 1;
  for (let x = 0; x <= canvas.width; x += 48) {
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, canvas.height);
    context.stroke();
  }
  for (let y = 0; y <= canvas.height; y += 48) {
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(canvas.width, y);
    context.stroke();
  }

  context.fillStyle = "rgba(255,255,255,.18)";
  context.beginPath();
  context.arc(110, 0, 52, 0, Math.PI * 2);
  context.fill();
  context.beginPath();
  context.arc(498, 14, 34, 0, Math.PI * 2);
  context.fill();

  const value = String(title || "未命名作品").trim();
  context.fillStyle = "#ffffff";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.font = "700 52px -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif";
  context.shadowColor = "rgba(27,52,71,.24)";
  context.shadowBlur = 8;
  const maxWidth = 438;
  const lines: string[] = [];
  let current = "";
  for (const character of value) {
    const candidate = current + character;
    if (current && context.measureText(candidate).width > maxWidth) {
      lines.push(current);
      current = character;
    } else {
      current = candidate;
    }
  }
  if (current) lines.push(current);
  const visibleLines = lines.slice(0, 3);
  const lineHeight = 70;
  const startY = 318 - ((visibleLines.length - 1) * lineHeight) / 2;
  visibleLines.forEach((line, index) => context.fillText(line, canvas.width / 2, startY + index * lineHeight));

  context.shadowBlur = 0;
  context.fillStyle = "rgba(255,255,255,.9)";
  context.font = "500 24px -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif";
  context.fillText(`${String(author || "佚名").trim()} 著`, canvas.width / 2, 638);
  return canvas.toDataURL("image/jpeg", 0.88);
}
