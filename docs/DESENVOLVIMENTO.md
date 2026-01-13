# Minha Jornada no Desenvolvimento do Agente Bancario Inteligente

## Sobre o Desenvolvedor

Este documento contém minhas reflexões pessoais sobre o desenvolvimento deste projeto, os desafios que enfrentei, as decisões que tomei e o aprendizado que obtive ao longo do caminho.

---

## O Desafio

Quando recebi este teste técnico, sabia que seria uma oportunidade única de mergulhar no universo de agentes de IA aplicados a um contexto bancário. O desafio não era apenas técnico, mas também conceitual: como criar um agente que fosse ao mesmo tempo inteligente, seguro, eficiente e, acima de tudo, humanizado?

---

## Principais Dificuldades Enfrentadas

### 1. Restringir o Agente ao Contexto Bancário

Um dos maiores desafios foi garantir que o agente se mantivesse estritamente no contexto bancário, sem desviar para assuntos fora do escopo. A natureza dos modelos de linguagem é responder a qualquer tipo de pergunta, então precisei implementar múltiplas camadas de proteção:

- **Filtros de palavras proibidas** para detectar e rejeitar tentativas de desvio de contexto
- **Prompts cuidadosamente estruturados** que reforçam constantemente o papel do agente como assistente bancário
- **Validação de intenções** que classifica as mensagens e só permite aquelas relacionadas aos serviços oferecidos
- **Respostas de redirecionamento educadas** quando o usuário tenta sair do escopo

Essa foi uma batalha constante entre deixar o agente suficientemente flexível para entender variações de linguagem natural e rígido o suficiente para não fugir do propósito.

### 2. Humanizar as Respostas do Agente

Criar respostas que não parecessem "robotizadas" foi outro grande desafio. O usuário final não deveria sentir que está conversando com uma máquina, mas sim com um atendente real do banco. Para isso:

- Implementei uma **camada de humanização** que transforma respostas técnicas em linguagem natural e acolhedora
- Configurei o agente para **personalizar as respostas** usando o nome do cliente quando disponível
- Criei **fluxos de conversa naturais** com saudações, despedidas e transições suaves entre assuntos
- Adicionei **sugestões contextuais** que antecipam as necessidades do cliente (por exemplo, sugerir a entrevista após uma solicitação de aumento negada)

### 3. Otimizar o Consumo de Tokens

O custo de tokens em APIs de LLM pode escalar rapidamente, especialmente em um sistema de atendimento com muitas interações. Precisei encontrar o equilíbrio entre qualidade das respostas e eficiência de consumo:

- **Compactei os prompts** substituindo prefixos verbosos por abreviações que o modelo entende igualmente bem
- **Reduzi instruções redundantes** mantendo apenas o essencial para o modelo compreender o contexto
- **Otimizei o histórico de conversas** limitando o tamanho e usando formatação mais enxuta
- **Implementei cache de respostas** para perguntas frequentes
- **Documentei todas as otimizações** no arquivo `otimizacao-tokens.md` com estimativas de economia

A pesquisa para essas otimizações me levou por vários vídeos no YouTube, documentações técnicas e muitas conversas com o Claude para entender as melhores práticas do mercado.

---

## Processo de Desenvolvimento

### Pesquisa e Aprendizado

Para construir este projeto, realizei extensa pesquisa em diversas fontes:

- **Documentação oficial** do FastAPI, LangChain e OpenAI
- **Vídeos técnicos** sobre otimização de prompts e engenharia de LLMs
- **Artigos e discussões** sobre boas práticas em sistemas de agentes
- **Função search do Claude** para tirar dúvidas pontuais e explorar alternativas

Todo o código gerado com assistência de IA foi cuidadosamente revisado, testado e validado por mim. Assumo total responsabilidade pelo que está sendo entregue, tendo pleno domínio e consciência de cada componente implementado.

### Testes Extensivos

Realizei diversos testes simulando múltiplos cenários:

- Fluxos completos de autenticação com dados válidos e inválidos
- Tentativas de burlar o contexto bancário
- Solicitações de aumento de limite em diferentes faixas de score
- Entrevistas financeiras com variações de perfil
- Consultas de câmbio com diferentes moedas
- Conversas naturais para testar a humanização

Acredito ter chegado a um resultado muito sólido com essa bateria de testes.

---

## Reflexões e Aprendizados

### O que Aprendi

Este projeto foi uma jornada de muito aprendizado:

1. **Arquitetura de Agentes**: Compreendi como estruturar sistemas com múltiplos agentes especializados que colaboram entre si através de um orquestrador central.

2. **Máquinas de Estado**: Aprendi a gerenciar fluxos de conversa complexos usando estados bem definidos e transições controladas.

3. **Engenharia de Prompts**: Descobri que menos é mais - prompts concisos e bem estruturados frequentemente superam prompts verbosos.

4. **Trade-offs de Design**: Entendi as escolhas entre flexibilidade (LLM) e determinismo (regras), optando por um sistema híbrido com fallback.

### Dúvidas que Permaneceram

Ainda tenho algumas dúvidas sobre qual seria o melhor design pattern para este tipo de projeto:

- **Orquestrador centralizado vs. Agentes autônomos**: Optei pelo orquestrador, mas me pergunto se agentes mais independentes teriam vantagens em escalabilidade.
- **Event Sourcing**: Seria benéfico para rastreabilidade completa das interações?
- **CQRS**: Faria sentido separar comandos de consultas neste contexto?

Essas são reflexões para continuar estudando e evoluindo como desenvolvedor.

---

## Sobre a Entrega

### Escalabilidade

Acredito que o projeto está bem estruturado para escalar:

- **Arquitetura modular** permite adicionar novos agentes facilmente
- **Serviços desacoplados** facilitam substituição de componentes (ex: trocar CSV por banco de dados)
- **Configurações via ambiente** possibilitam ajustes sem alteração de código
- **Docker ready** para deploy em qualquer infraestrutura

### Nota para os Recrutadores

Coloquei US$ 10 de crédito na OpenAI para que vocês possam testar o projeto com o agente de IA funcionando plenamente. Sintam-se à vontade para explorar todas as funcionalidades!

O sistema também funciona perfeitamente sem a API da OpenAI, utilizando o fallback baseado em regras, mas a experiência com o LLM é significativamente mais rica e demonstra melhor o potencial da solução.

---

## Considerações Finais

Desenvolver este projeto após meu horário de trabalho foi um desafio considerável, mas também uma experiência extremamente gratificante. Cada dificuldade superada representou um aprendizado valioso.

Reconheço que sempre há espaço para melhorias - nenhum software está verdadeiramente "pronto". Porém, acredito firmemente que esta entrega cumpre com os requisitos propostos e demonstra minha capacidade de:

- Resolver problemas complexos com soluções pragmáticas
- Pesquisar e aprender novas tecnologias rapidamente
- Produzir código limpo, testável e bem documentado
- Pensar em escalabilidade e manutenibilidade desde o início

Agradeço a oportunidade de participar deste processo seletivo e estou à disposição para discutir qualquer aspecto do projeto.

---

*Desenvolvido com dedicação, muito café e algumas madrugadas.*
