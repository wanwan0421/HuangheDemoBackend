import 'global-agent/bootstrap';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import * as express from 'express';
import * as path from 'path';
import * as fs from 'fs';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // 允许跨域
  app.enableCors({
    // allowed origins
    origin: 'http://localhost:5173',
    // allowed cookies
    credentials: true,
    // allowed methods
    methods: 'GET,HEAD,PUT,PATCH,POST,DELETE,OPTIONS',
    // allowed headers
    allowedHeaders: 'Content-Type, Accept, Authorization',
  });

  // 静态资源映射
  const uploadRoot = path.resolve(__dirname, '../model-scripts/uploads');

  // 映射 /uploads 路径到上传目录
  app.use(
    '/uploads',
    express.static(uploadRoot, {
      setHeaders: (res) => {
        // 显式允许前端来源访问静态文件
        res.set('Access-Control-Allow-Origin', 'http://localhost:5173');
        res.set('Access-Control-Allow-Methods', 'GET, OPTIONS');
        res.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');
      },
    })
  );

  await app.listen(process.env.PORT ?? 3000);
}
bootstrap();
