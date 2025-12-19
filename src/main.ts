import 'global-agent/bootstrap';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // start CORS
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
  await app.listen(process.env.PORT ?? 3000);
}
bootstrap();
