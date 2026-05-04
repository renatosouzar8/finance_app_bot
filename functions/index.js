const { onCall, onRequest } = require("firebase-functions/v2/https");
const admin = require("firebase-admin");
const { PluggyClient } = require("pluggy-sdk");
const axios = require("axios");

admin.initializeApp();
const db = admin.firestore();

const TELEGRAM_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const APP_ID = "default-app-id";

// Helper para instanciar o PluggyClient usando as environment variables
const getPluggyClient = () => {
  const clientId = process.env.PLUGGY_CLIENT_ID;
  const clientSecret = process.env.PLUGGY_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    throw new Error("Missing Pluggy credentials in environment variables.");
  }
  return new PluggyClient({ clientId, clientSecret });
};

const TELEGRAM_URL = process.env.TELEGRAM_BOT_URL || "http://localhost:5000/webhook"; // Url do seu webhook bot caso tenha

/**
 * Endpoint para gerar um token de conexão pro Widget do Frontend
 */
exports.createConnectToken = onCall({ cors: true }, async (request) => {
  if (!request.auth) throw new Error("unauthenticated");
  
  try {
    const client = getPluggyClient();
    // Gera token válido para o usuário
    const dataResponse = await client.createConnectToken();
    return { accessToken: dataResponse.accessToken };
  } catch (error) {
    console.error("Error creating connect token:", error);
    throw new Error(error.message);
  }
});

/**
 * Endpoint para trocar public_token por item_id e salvar conexão
 */
exports.exchangeToken = onCall({ cors: true }, async (request) => {
  // Verifica se usuário está logado
  if (!request.auth) {
    throw new Error("User must be authenticated.");
  }
  
  const { itemId } = request.data;
  
  if (!itemId) {
      throw new Error("Missing itemId from frontend.");
  }

  const userId = request.auth.uid;
  const appId = "default-app-id"; // Match database architecture

  try {
    // 1. Salvar o ID da conexão no documento do usuário (importante para o dashboard)
    const userRef = db.collection("artifacts").doc(appId).collection("users").doc(userId);
    await userRef.set({
        pluggyConnectionId: itemId,
        updatedAt: admin.firestore.FieldValue.serverTimestamp()
    }, { merge: true });

    // 2. Salvar mapeamento global de itemId -> userId para o Webhook
    await db.collection("artifacts").doc(appId).collection("connections").doc(itemId).set({
        userId: userId,
        createdAt: admin.firestore.FieldValue.serverTimestamp()
    });

    // 3. Puxar transações iniciais imediatamente para feedback instantâneo
    console.log(`Buscando transações iniciais para itemId: ${itemId}`);
    const client = getPluggyClient();
    try {
        const accounts = await client.fetchAccounts(itemId);
        console.log(`Encontradas ${accounts.results.length} contas para o item ${itemId}`);
        
        const allTransactions = [];
        for (const account of accounts.results) {
            console.log(`Buscando transações para conta: ${account.id} (${account.name})`);
            const txs = await client.fetchTransactions(account.id);
            console.log(`Encontradas ${txs.results.length} transações para conta ${account.id}`);
            
            for (const tx of txs.results) {
                allTransactions.push(tx);
                const txRef = db.collection("artifacts").doc(appId).collection("users").doc(userId).collection("transactions");
                const existing = await txRef.where("external_id", "==", tx.id).get();
                if (existing.empty) {
                    await txRef.add({
                        description: tx.description,
                        amount: Math.abs(tx.amount),
                        date: admin.firestore.Timestamp.fromDate(new Date(tx.date)),
                        type: tx.amount < 0 ? "expense" : "income",
                        category: "Ajuste Inicial",
                        source_type: "open_finance",
                        sync_status: "confirmed",
                        external_id: tx.id,
                        userId: userId,
                        createdAt: admin.firestore.FieldValue.serverTimestamp()
                    });
                }
            }
        }
        
        // 4. Notificar via Telegram (Fila de Notificação) - Apenas após sucesso
        const mappingDoc = await db.collection("artifacts").doc(APP_ID).collection("user_mappings").where("firebaseUserId", "==", userId).get();
        if (!mappingDoc.empty) {
            const telegramId = mappingDoc.docs[0].id;
            console.log(`Enfileirando notificações iniciais (${Math.min(allTransactions.length, 5)} de ${allTransactions.length}) para Telegram ID: ${telegramId}`);
            
            // Limitamos a 5 mensagens no início para evitar bloqueio do Telegram
            const recentTransactions = allTransactions.slice(0, 5);
            for (const tx of recentTransactions) {
                await db.collection("artifacts").doc(APP_ID).collection("notification_queue").add({
                    telegramId: telegramId,
                    firebaseUserId: userId,
                    transaction: {
                        id: tx.id,
                        description: tx.description,
                        amount: tx.amount,
                        category: tx.category || "Open Finance"
                    },
                    status: "pending",
                    createdAt: admin.firestore.FieldValue.serverTimestamp()
                });
            }
        }
    } catch (pullError) {
        console.error("Erro no pull inicial:", pullError);
    }

    return { success: true, itemId: itemId, transactionsFound: allTransactions.length };
  } catch (error) {
    console.error("Error exchanging token:", error);
    throw new Error(error.message);
  }
});

/**
 * Lista as conexões vinculadas ao usuário
 */
exports.listUserConnections = onCall({ cors: true }, async (request) => {
  if (!request.auth) throw new Error("unauthenticated");
  const userId = request.auth.uid;
  
  try {
    const snapshots = await db.collection("artifacts").doc(APP_ID).collection("connections")
                        .where("userId", "==", userId).get();
    
    if (snapshots.empty) return { connections: [] };

    const client = getPluggyClient();
    const connections = [];

    for (const doc of snapshots.docs) {
      const itemId = doc.id;
      try {
        const item = await client.fetchItem(itemId);
        connections.push({
          id: itemId,
          status: item.status,
          updatedAt: item.updatedAt,
          institution: item.connector.name,
          institutionImageUrl: item.connector.imageUrl
        });
      } catch (e) {
        console.error(`Erro ao buscar item ${itemId} no Pluggy:`, e);
      }
    }

    return { connections };
  } catch (error) {
    console.error("Error listing connections:", error);
    throw new Error(error.message);
  }
});

/**
 * Remove uma conexão do Pluggy e do Firestore
 */
exports.deleteConnection = onCall({ cors: true }, async (request) => {
  if (!request.auth) throw new Error("unauthenticated");
  const userId = request.auth.uid;
  const { itemId } = request.data;

  if (!itemId) throw new Error("Missing itemId");

  try {
    const connRef = db.collection("artifacts").doc(APP_ID).collection("connections").doc(itemId);
    const connDoc = await connRef.get();
    
    if (!connDoc.exists || connDoc.data().userId !== userId) {
      throw new Error("Connection not found or unauthorized");
    }

    // 1. Deletar no Pluggy
    const client = getPluggyClient();
    try {
      await client.deleteItem(itemId);
    } catch (e) {
      console.warn("Could not delete from Pluggy (might already be gone):", e);
    }

    // 2. Remover do Firestore
    await connRef.delete();

    return { success: true };
  } catch (error) {
    console.error("Error deleting connection:", error);
    throw new Error(error.message);
  }
});

/**
 * Webhook Receptor para atualizações da Pluggy
 * Recebe notificações, ex: TRANSACTIONS_UPDATED
 */
exports.webhookReceiver = onRequest({ cors: true }, async (req, res) => {
  // Webhooks geralmente são POSTs
  if (req.method !== "POST") {
    return res.status(405).send("Method Not Allowed");
  }

  try {
    const { event, itemId } = req.body;
    console.log(`Webhook recebido: ${event} para o item ${itemId}`);
    
    // Filtramos atualizações relevantes
    const validEvents = ["item/updated", "transactions/updated", "item/created"];
    if (validEvents.includes(event)) {
       console.log(`Processando evento ${event} para Connection: ${itemId}`);
       
       // 1. Achar o userId dono desta conexão
       const connDoc = await db.collection("artifacts").doc(APP_ID).collection("connections").doc(itemId).get();
       if (!connDoc.exists) {
           console.log("Connection not mapped to any user.");
           return res.status(200).send("No mapping found");
       }
       const { userId } = connDoc.data();

       const client = getPluggyClient();
       const accounts = await client.fetchAccounts(itemId);
       
       let allTransactions = [];
       for (const account of accounts.results) {
         const txs = await client.fetchTransactions(account.id);
         allTransactions.push(...txs.results);
       }

       // 2. Processar novas transações e notificar Telegram
       for (const tx of allTransactions.slice(0, 3)) { // Limitado a 3 para evitar flood no teste
           const externalId = tx.id;
           const txRef = db.collection("artifacts").doc(APP_ID).collection("users").doc(userId).collection("transactions");
           
           // Check idempotency
           const existing = await txRef.where("external_id", "==", externalId).get();
           if (existing.empty) {
               // Salvar como pending_review
               const newTx = {
                   description: tx.description,
                   raw_description: tx.description,
                   amount: Math.abs(tx.amount),
                   date: admin.firestore.Timestamp.fromDate(new Date(tx.date)),
                   type: tx.amount < 0 ? "expense" : "income",
                   category: "Pendente",
                   source_type: "open_finance",
                   sync_status: "pending_review",
                   external_id: externalId,
                   connection_id: itemId,
                   userId: userId,
                   createdAt: admin.firestore.FieldValue.serverTimestamp()
               };
               const docRef = await txRef.add(newTx);

               // Notificar Telegram
               if (TELEGRAM_TOKEN && newTx.type === "expense") {
                   try {
                       // 3. Fila de Notificação para o Bot (via Firestore)
                       const mappingDoc = await db.collection("artifacts").doc(APP_ID).collection("user_mappings").where("firebaseUserId", "==", userId).get();
                                              if (!mappingDoc.empty) {
                            const telegramId = mappingDoc.docs[0].id;
                            console.log(`Enfileirando notificação Webhook para Telegram ID: ${telegramId}`);
                            
                            await db.collection("artifacts").doc(APP_ID).collection("notification_queue").add({
                                telegramId: telegramId,
                                firebaseUserId: userId,
                                transaction: {
                                    id: tx.id,
                                    description: tx.description,
                                    amount: tx.amount,
                                    category: tx.category || "Open Finance"
                                },
                                status: "pending",
                                createdAt: admin.firestore.FieldValue.serverTimestamp()
                            });
                        } else {
                            console.log("No telegram mapping found for user:", userId);
                        }
                   } catch (tgError) {
                       console.error("Error sending Telegram message:", tgError);
                   }
               }
           }
       }
    }

    res.status(200).send("Webhook received");
  } catch (error) {
    console.error("Webhook Error:", error);
    res.status(500).send("Internal Server Error");
  }
});
